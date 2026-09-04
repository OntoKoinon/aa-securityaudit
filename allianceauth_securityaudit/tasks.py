import logging

from django.db import transaction

try:
    from celery import shared_task
except Exception:  # pragma: no cover
    def shared_task(*_args, **_kwargs):
        def deco(func):
            return func

        return deco

from .models import AuditPolicy, AuditRun
from .services.audit_engine import AuditEngine
from .services.automation import queue_new_join_audits
from .services.exceptions import MissingScopesError

LOGGER = logging.getLogger(__name__)


def enqueue_task(task, *args, **kwargs):
    delay = getattr(task, "delay", None)
    if callable(delay):
        return delay(*args, **kwargs)
    return task(*args, **kwargs)


def _update_parent_run(child_run):
    parent = child_run.parent_run
    if not parent:
        return
    siblings = parent.child_runs.all()
    total = siblings.count()
    if not total:
        return
    terminal_statuses = {
        AuditRun.STATUS_COMPLETE,
        AuditRun.STATUS_INCOMPLETE_MISSING_SCOPES,
        AuditRun.STATUS_FAILED,
    }
    terminal = [s for s in siblings if s.status in terminal_statuses]
    terminal_count = len(terminal)

    if terminal_count == total:
        total_score = sum(s.risk_score for s in siblings)
        risk_level = AuditEngine._risk_level(total_score)
        summary_parts = []
        for s in siblings:
            name = s.target.character_name or f"Run #{s.id}"
            if s.status == AuditRun.STATUS_COMPLETE:
                summary_parts.append(f"{name}: {s.risk_level} ({s.risk_score})")
            elif s.status == AuditRun.STATUS_INCOMPLETE_MISSING_SCOPES:
                summary_parts.append(f"{name}: missing scopes")
            else:
                summary_parts.append(f"{name}: failed")
        parent.mark_complete(
            summary=f"{terminal_count} individual audits complete — " + "; ".join(summary_parts),
            risk_score=total_score,
            risk_level=risk_level,
        )
    else:
        parent.set_progress(
            terminal_count,
            total,
            f"Individual audits {terminal_count}/{total} complete",
        )


@shared_task(name="securityaudit.process_audit_run")
def process_audit_run(audit_run_id):
    try:
        audit_run = AuditRun.objects.select_related("target").get(pk=audit_run_id)
    except AuditRun.DoesNotExist:
        LOGGER.warning("AuditRun %s not found", audit_run_id)
        return

    def progress_callback(current, total, message, details=None):
        # Throttle: skip the DB round-trip if the progress percentage
        # hasn't changed. The message may differ but we only persist
        # when the integer percentage advances, cutting dozens of
        # SELECT+UPDATE pairs down to a handful per audit.
        pct = int((current / max(total, 1)) * 100) if total else 0
        last = progress_callback._last_pct
        if last is not None and pct == last:
            return
        progress_callback._last_pct = pct
        try:
            refreshed = AuditRun.objects.get(pk=audit_run_id)
            refreshed.set_progress(current, total, message, details=details)
        except AuditRun.DoesNotExist:
            return

    progress_callback._last_pct = None

    policy = AuditPolicy.get_solo()
    engine = AuditEngine(policy, progress_callback=progress_callback, policy_overrides=audit_run.policy_overrides)

    with transaction.atomic():
        audit_run.set_running()
        audit_run.findings.all().delete()
        audit_run.counterparties.all().delete()
        audit_run.capital_ship_observations.all().delete()
    progress_callback(8, 100, "Cleared previous findings")

    try:
        result = engine.run(audit_run)
    except MissingScopesError as ex:
        audit_run.mark_incomplete_missing_scopes(ex.scopes, str(ex))
        _update_parent_run(audit_run)
        return
    except Exception as ex:
        audit_run.mark_failed(str(ex))
        _update_parent_run(audit_run)
        return

    if result.missing_scopes:
        audit_run.mark_incomplete_missing_scopes(result.missing_scopes)
        _update_parent_run(audit_run)
        return

    child_ids = getattr(result, "child_run_ids", None) or []
    if child_ids:
        audit_run.set_progress(
            0,
            len(child_ids),
            f"Waiting for {len(child_ids)} individual audits",
        )
    else:
        audit_run.mark_complete(
            summary=result.summary,
            risk_score=result.risk_score,
            risk_level=result.risk_level,
        )
    _update_parent_run(audit_run)

    for child_id in child_ids:
        enqueue_task(process_audit_run, child_id)


@shared_task(name="securityaudit.process_new_joins")
def process_new_joins():
    policy = AuditPolicy.get_solo()
    if not policy.enabled or not policy.automation_enabled:
        return 0

    queued_runs = queue_new_join_audits(policy)

    for run in queued_runs:
        result = enqueue_task(process_audit_run, run.id)
        run.task_id = getattr(result, "id", "")
        run.save(update_fields=["task_id"])

    retryable = AuditRun.objects.filter(status=AuditRun.STATUS_INCOMPLETE_MISSING_SCOPES, automated=True)
    for run in retryable:
        result = enqueue_task(process_audit_run, run.id)
        run.task_id = getattr(result, "id", "")
        run.save(update_fields=["task_id"])

    return len(queued_runs)
