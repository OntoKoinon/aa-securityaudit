from collections import Counter
from datetime import timedelta
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.utils import timezone
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import AuditPolicyForm, AuditRunForm, EnemyEntityForm, FinancialExceptionForm
from .models import (
    AuditPolicy,
    AuditRelationshipCounterparty,
    AuditRun,
    AuditSummaryLink,
    AuditSummaryView,
    AuditTarget,
    EnemyEntity,
    FinancialException,
)
from .services.esi_client import EsiClient
from .services.memberaudit_adapter import MemberAuditAdapter
try:
    from celery.result import AsyncResult
except Exception:  # pragma: no cover
    AsyncResult = None
from .tasks import _update_parent_run, enqueue_task, process_audit_run, process_new_joins


def _initiator_display(user):
    if not user:
        return "", "Automated"
    main = getattr(getattr(user, "profile", None), "main_character", None)
    if main:
        char_id = getattr(main, "character_id", None)
        char_name = getattr(main, "character_name", None)
        if char_id:
            return MemberAuditAdapter._portrait_url(char_id), (char_name or str(user))
    return "", str(user)


def _corporation_summary(run):
    if run.target.target_type != AuditTarget.TARGET_CORP:
        return run.summary
    total = run.child_runs.count()
    missing = run.child_runs.filter(status=AuditRun.STATUS_INCOMPLETE_MISSING_SCOPES).count()
    critical_qs = run.child_runs.filter(risk_level="critical").select_related("target")
    critical_names = [c.target.character_name or str(c.target) for c in critical_qs]
    critical_str = ", ".join(critical_names) if critical_names else "none"
    return f"Audited {total} members; {missing} missing ESI scopes; critical: {critical_str}"


def _is_admin(user):
    return user.has_perm("securityaudit.administrate")


def _user_declared_corp_ids(user):
    corp_ids = set()
    profile = getattr(user, "profile", None)
    main = getattr(profile, "main_character", None) if profile else None
    if main:
        corp_id = MemberAuditAdapter._extract_int(main, "corporation_id", "corp_id", "corporation")
        if corp_id:
            corp_ids.add(int(corp_id))
    return corp_ids


def _run_matches_user_corp(run, user_corp_ids):
    if not user_corp_ids:
        return False
    target = getattr(run, "target", None)
    if target and target.target_type == AuditTarget.TARGET_CORP and target.corp_id in user_corp_ids:
        return True
    parent = getattr(run, "parent_run", None)
    if not parent:
        parent = (
            AuditRun.objects.select_related("target").filter(pk=getattr(run, "parent_run_id", None)).first()
        )
    parent_target = getattr(parent, "target", None)
    return bool(
        parent_target
        and parent_target.target_type == AuditTarget.TARGET_CORP
        and parent_target.corp_id in user_corp_ids
    )


def _corp_visibility_q(user_corp_ids):
    if not user_corp_ids:
        return Q(pk__in=[])
    return Q(
        target__target_type=AuditTarget.TARGET_CORP,
        target__corp_id__in=user_corp_ids,
    ) | Q(
        parent_run__target__target_type=AuditTarget.TARGET_CORP,
        parent_run__target__corp_id__in=user_corp_ids,
    )


def _can_view_run(user, run):
    if _is_admin(user):
        return True
    if run.automated or bool(run.started_by and run.started_by == user):
        return True
    return _run_matches_user_corp(run, _user_declared_corp_ids(user))


def _get_valid_summary_link(audit_run, token):
    if not token:
        return None
    try:
        link = AuditSummaryLink.objects.get(audit_run=audit_run, token=token)
    except AuditSummaryLink.DoesNotExist:
        return None
    if link.expires_at and link.expires_at < timezone.now():
        return None
    return link


def _disclosed_alts(target, run=None, include_target=False):
    def _normalize_id(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _lookup_name(names, entity_id):
        if entity_id is None:
            return None
        return names.get(entity_id) or names.get(str(entity_id))

    if target.target_type != AuditTarget.TARGET_INDIVIDUAL or not target.character_id:
        return []
    user = MemberAuditAdapter.get_user_for_character_id(target.character_id)
    if not user:
        return []
    alt_ids = MemberAuditAdapter.get_user_declared_character_ids(user)
    if not alt_ids:
        return []
    if not include_target:
        alt_ids.discard(target.character_id)
        if not alt_ids:
            return []
    elif target.character_id:
        alt_ids.add(int(target.character_id))

    # Debug counters to help operators confirm that contract ingestion is
    # working for each declared alt.
    contract_debug = {
        int(alt_id): {
            "contracts_found": 0,
            "contracts_with_hulls_found": 0,
            "hull_units_found": 0,
            "audit_contract_units_recorded": 0,
        }
        for alt_id in alt_ids
    }

    character_model = MemberAuditAdapter._get_model("memberaudit", "Character")
    contract_model = MemberAuditAdapter._get_model("memberaudit", "CharacterContract")
    if character_model is not None and contract_model is not None:
        try:
            from .services.audit_analysis.capital_ships import CAPITAL_SHIPS, CAPITAL_SHIP_GROUPS

            capital_type_ids = set(CAPITAL_SHIPS.keys())
            capital_group_ids = set(CAPITAL_SHIP_GROUPS)
            ma_chars = list(
                character_model.objects.select_related("eve_character").filter(
                    eve_character__character_id__in=alt_ids
                )
            )
            if ma_chars:
                contracts = (
                    contract_model.objects.select_related("character__eve_character")
                    .prefetch_related("items__eve_type__eve_group")
                    .filter(character__in=ma_chars, status__in=["OS", "IP"])
                )
                try:
                    contracts = contracts.filter(
                        Q(date_expired__isnull=True) | Q(date_expired__gte=timezone.now())
                    )
                except Exception:
                    pass
                for contract in contracts:
                    ma_char = getattr(contract, "character", None)
                    eve_char = getattr(ma_char, "eve_character", None) if ma_char else None
                    owner_char_id = getattr(eve_char, "character_id", None)
                    if owner_char_id is None:
                        continue
                    owner_char_id = int(owner_char_id)
                    if owner_char_id not in contract_debug:
                        continue
                    issuer_id = getattr(contract, "issuer_id", None)
                    if issuer_id is not None and int(issuer_id) != owner_char_id:
                        continue

                    stats = contract_debug[owner_char_id]
                    stats["contracts_found"] += 1

                    has_hull = False
                    hull_units = 0
                    for item in contract.items.all():
                        if not getattr(item, "is_included", True):
                            continue
                        type_id = getattr(item, "eve_type_id", None) or getattr(item, "type_id", None)
                        if not type_id:
                            continue
                        is_capital_type = int(type_id) in capital_type_ids
                        if not is_capital_type:
                            eve_type = getattr(item, "eve_type", None)
                            group_id = getattr(eve_type, "eve_group_id", None) if eve_type else None
                            if group_id is None and eve_type is not None:
                                eve_group = getattr(eve_type, "eve_group", None)
                                group_id = getattr(eve_group, "id", None)
                            is_capital_type = group_id in capital_group_ids
                        if not is_capital_type:
                            continue
                        has_hull = True
                        quantity = getattr(item, "quantity", None)
                        is_singleton = bool(getattr(item, "is_singleton", False))
                        try:
                            quantity = int(quantity) if quantity is not None else 0
                        except (TypeError, ValueError):
                            quantity = 0
                        quantity = max(quantity, 1 if is_singleton else 0, 1)
                        hull_units += quantity
                    if has_hull:
                        stats["contracts_with_hulls_found"] += 1
                        stats["hull_units_found"] += max(hull_units, 1)
        except Exception:
            pass

    if run is not None:
        try:
            for obs in run.capital_ship_observations.all():
                char_id = getattr(obs, "character_id", None)
                if char_id in contract_debug:
                    contract_debug[char_id]["audit_contract_units_recorded"] += int(
                        getattr(obs, "contract_count", 0) or 0
                    )
        except Exception:
            pass

    resolved = EsiClient().resolve_names(alt_ids) or {}
    esi = EsiClient()
    alts = []
    corp_ids = set()
    alliance_ids = set()
    for alt_id in sorted(alt_ids):
        character_name = resolved.get(alt_id) or ""
        corp_id = None
        alliance_id = None
        birthday = None

        snapshot = MemberAuditAdapter.get_character_snapshot(character_id=alt_id)
        if snapshot:
            if not character_name:
                character_name = snapshot.get("name") or ""
            corp_id = _normalize_id(snapshot.get("corporation_id"))
            alliance_id = _normalize_id(snapshot.get("alliance_id"))
        try:
            # Pull birthday for age sorting (oldest first). ESI calls are cached.
            char = esi.get_character(alt_id)
            if not character_name:
                character_name = char.get("name") or ""
            if not corp_id:
                corp_id = _normalize_id(char.get("corporation_id"))
            if not alliance_id:
                alliance_id = _normalize_id(char.get("alliance_id"))
            birthday = EsiClient.parse_esi_time(char.get("birthday"))
        except Exception:
            pass
        if not character_name or not corp_id:
            try:
                char = esi.get_character(alt_id)
                if not character_name:
                    character_name = char.get("name") or ""
                if not corp_id:
                    corp_id = _normalize_id(char.get("corporation_id"))
                if not alliance_id:
                    alliance_id = _normalize_id(char.get("alliance_id"))
                if birthday is None:
                    birthday = EsiClient.parse_esi_time(char.get("birthday"))
            except Exception:
                pass

        if not character_name:
            character_name = str(alt_id)
        if corp_id:
            corp_ids.add(corp_id)
        if alliance_id:
            alliance_ids.add(alliance_id)

        alts.append(
            {
                "character_id": alt_id,
                "character_name": character_name,
                "is_target": bool(target.character_id and int(target.character_id) == int(alt_id)),
                "portrait_url": MemberAuditAdapter._portrait_url(alt_id),
                "corp_id": corp_id,
                "corp_name": str(corp_id or ""),
                "corp_logo_url": "",
                "alliance_id": alliance_id,
                "alliance_name": "",
                "alliance_logo_url": "",
                "birthday": birthday,
                "contracts_found": contract_debug.get(alt_id, {}).get("contracts_found", 0),
                "contracts_with_hulls_found": contract_debug.get(alt_id, {}).get(
                    "contracts_with_hulls_found", 0
                ),
                "hull_units_found": contract_debug.get(alt_id, {}).get("hull_units_found", 0),
                "audit_contract_units_recorded": contract_debug.get(alt_id, {}).get(
                    "audit_contract_units_recorded", 0
                ),
            }
        )

    ids_to_resolve = set(corp_ids) | set(alliance_ids)
    if ids_to_resolve:
        names = esi.resolve_names(ids_to_resolve) or {}
        corp_summaries = MemberAuditAdapter.get_corporation_summaries(list(corp_ids))
        corp_by_id = {_normalize_id(c.get("corporation_id")): c for c in corp_summaries or []}
        unresolved_corp_ids = set()
        for alt in alts:
            cid = alt.get("corp_id")
            if cid:
                corp = corp_by_id.get(cid)
                if corp and corp.get("name"):
                    alt["corp_name"] = corp["name"]
                else:
                    resolved_name = _lookup_name(names, cid)
                    if resolved_name:
                        alt["corp_name"] = resolved_name
                if alt.get("corp_name") in ("", str(cid)):
                    unresolved_corp_ids.add(cid)
                alt["corp_logo_url"] = MemberAuditAdapter._corp_logo_url(cid)
            aid = alt.get("alliance_id")
            if aid:
                alt["alliance_name"] = _lookup_name(names, aid) or str(aid)
                alt["alliance_logo_url"] = f"https://images.evetech.net/alliances/{aid}/logo?size=64"

        if unresolved_corp_ids:
            resolved_corp_names = {}
            for corp_id in unresolved_corp_ids:
                try:
                    corp = esi.get_corporation(corp_id)
                except Exception:
                    continue
                corp_name = (corp or {}).get("name")
                if corp_name:
                    resolved_corp_names[corp_id] = corp_name
            if resolved_corp_names:
                for alt in alts:
                    cid = alt.get("corp_id")
                    if cid in resolved_corp_names:
                        alt["corp_name"] = resolved_corp_names[cid]

    # Keep the audited main visible in this section and pin it first.
    alts.sort(
        key=lambda a: (
            0 if a.get("is_target") else 1,
            a.get("birthday") is None,
            a.get("birthday") or timezone.now(),
            (a.get("character_name") or "").lower(),
            int(a.get("character_id") or 0),
        )
    )

    return alts


def _child_audit_rows(run, detail=False):
    if run.target.target_type != AuditTarget.TARGET_CORP:
        return []
    rows = []
    url_name = "securityaudit:audit_detail" if detail else "securityaudit:audit_summary"
    for child in run.child_runs.select_related("target").order_by("target__character_name"):
        rows.append(
            {
                "id": child.id,
                "character_name": child.target.character_name or "Unknown",
                "portrait_url": MemberAuditAdapter._portrait_url(child.target.character_id),
                "status_display": child.get_status_display(),
                "risk_level": child.risk_level,
                "risk_score": child.risk_score,
                "url": reverse(url_name, kwargs={"audit_id": child.id}),
            }
        )
    return rows


def _active_new_join_audit_counts():
    from django.utils import timezone
    from datetime import timedelta

    active_qs = AuditRun.objects.filter(
        automated=True,
        status__in=[AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING],
    )
    running_qs = active_qs.filter(status=AuditRun.STATUS_RUNNING)
    queued_count = active_qs.filter(status=AuditRun.STATUS_QUEUED).count()

    running_count = 0
    stale_running = []
    stale_threshold = timezone.now() - timedelta(minutes=30)
    for run in running_qs:
        last_activity = run.started_at or run.created_at
        if last_activity and last_activity < stale_threshold:
            stale_running.append(run)
        else:
            running_count += 1

    return {
        "active_count": running_count + queued_count,
        "running_count": running_count,
        "queued_count": queued_count,
        "stale_running": stale_running,
    }


@permission_required("securityaudit.view_dashboard", raise_exception=True)
def dashboard(request):
    runs_qs = AuditRun.objects.select_related("target", "started_by").prefetch_related(
        "summary_views__user"
    ).order_by("-created_at")
    if not _is_admin(request.user):
        user_corp_ids = _user_declared_corp_ids(request.user)
        runs_qs = runs_qs.filter(
            Q(started_by=request.user) | Q(automated=True) | _corp_visibility_q(user_corp_ids)
        )

    status = request.GET.get("status", "").strip()
    risk_levels = [r.strip() for r in request.GET.getlist("risk_level") if r.strip()]
    target_type = request.GET.get("target_type", "").strip()
    q = request.GET.get("q", "").strip()
    if status:
        runs_qs = runs_qs.filter(status=status)
    if risk_levels:
        runs_qs = runs_qs.filter(risk_level__in=risk_levels)
    if target_type:
        runs_qs = runs_qs.filter(target__target_type=target_type)
    if q:
        q_filter = Q(target__character_name__icontains=q) | Q(target__corp_name__icontains=q)
        try:
            q_id = int(q)
            q_filter |= Q(target__character_id=q_id) | Q(target__corp_id=q_id)
        except (ValueError, TypeError):
            pass
        runs_qs = runs_qs.filter(q_filter)

    # Sortable columns
    sort_map = {
        "id": "id",
        "-id": "-id",
        "created": "created_at",
        "-created": "-created_at",
        "risk_score": "risk_score",
        "-risk_score": "-risk_score",
        "status": "status",
        "-status": "-status",
    }
    sort_param = request.GET.get("sort", "").strip()
    order_by = sort_map.get(sort_param, "-created_at")
    runs_qs = runs_qs.order_by(order_by)

    per_page_choices = [10, 25, 50, 100]
    try:
        per_page = int(request.GET.get("per_page", "10"))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in per_page_choices:
        per_page = 10

    paginator = Paginator(runs_qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    job_counts = _active_new_join_audit_counts()
    target_meta = _dashboard_target_meta(list(page_obj.object_list))

    initiator_meta = {}
    viewer_avatars = {}
    for run in page_obj.object_list:
        portrait, name = _initiator_display(run.started_by)
        initiator_meta[run.id] = {"portrait_url": portrait, "name": name}
        seen = set()
        avatars = []
        for view in run.summary_views.all():
            user = view.user
            if not user or user.id in seen:
                continue
            seen.add(user.id)
            p, n = _initiator_display(user)
            if p:
                avatars.append({"portrait_url": p, "name": n})
        viewer_avatars[run.id] = avatars

    context = {
        "page_obj": page_obj,
        "target_meta": target_meta,
        "initiator_meta": initiator_meta,
        "viewer_avatars": viewer_avatars,
        "per_page": per_page,
        "per_page_choices": per_page_choices,
        "status": status,
        "risk_level": risk_levels,
        "target_type": target_type,
        "q": q,
        "sort": sort_param,
        "request": request,
        "statuses": [v[0] for v in AuditRun.STATUS_CHOICES],
        "risk_levels": ["low", "medium", "high", "critical"],
        "target_types": [
            {"value": "", "label": "All"},
            {"value": AuditTarget.TARGET_INDIVIDUAL, "label": "Individual"},
            {"value": AuditTarget.TARGET_CORP, "label": "Corporation"},
        ],
        "active_new_join_jobs_count": job_counts["active_count"],
        "active_new_join_running_count": job_counts["running_count"],
        "active_new_join_queued_count": job_counts["queued_count"],
        "active_nav": "dashboard",
        "form": AuditRunForm(initial={"target_type": AuditTarget.TARGET_INDIVIDUAL}),
    }
    return render(request, "securityaudit/dashboard.html", context)


@permission_required("securityaudit.view_dashboard", raise_exception=True)
@require_http_methods(["GET"])
def dashboard_live_status(request):
    counts = _active_new_join_audit_counts()
    active_count = counts["active_count"]
    if active_count:
        message = (
            f"New-join processing is active: {counts['running_count']} running, "
            f"{counts['queued_count']} queued."
        )
    else:
        message = "No active new-join processing jobs."

    return JsonResponse(
        {
            "active_count": active_count,
            "running_count": counts["running_count"],
            "queued_count": counts["queued_count"],
            "stale_running_count": len(counts.get("stale_running", [])),
            "message": message,
        }
    )


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["GET"])
def audit_jobs(request):
    from django.utils import timezone
    from datetime import timedelta

    active_runs = AuditRun.objects.filter(
        status__in=[
            AuditRun.STATUS_QUEUED,
            AuditRun.STATUS_RUNNING,
        ]
    ).select_related("target").order_by("-created_at")
    if not _is_admin(request.user):
        user_corp_ids = _user_declared_corp_ids(request.user)
        active_runs = active_runs.filter(Q(started_by=request.user) | _corp_visibility_q(user_corp_ids))

    stale_threshold = timezone.now() - timedelta(minutes=30)
    stale_count = 0
    for run in active_runs:
        last_activity = run.started_at or run.created_at
        run.is_stale = bool(
            run.status == AuditRun.STATUS_RUNNING and last_activity and last_activity < stale_threshold
        )
        if run.is_stale:
            stale_count += 1
        run.has_findings = run.findings.exists()
        run.has_counterparties = run.counterparties.exists()

    return render(
        request,
        "securityaudit/audit_jobs.html",
        {
            "runs": active_runs,
            "stale_count": stale_count,
            "active_nav": "dashboard",
        },
    )


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["POST"])
def audit_recover_stale(request):
    from django.utils import timezone
    from datetime import timedelta

    stale_threshold = timezone.now() - timedelta(minutes=30)
    stale_runs = list(
        AuditRun.objects.filter(
            status=AuditRun.STATUS_RUNNING,
            started_at__lt=stale_threshold,
        ).select_related("target")
    )
    recovered = 0
    for run in stale_runs:
        run.mark_failed("Stale run recovered by admin")
        _update_parent_run(run)
        recovered += 1

    if recovered:
        messages.success(request, f"Recovered {recovered} stale audit run(s).")
    else:
        messages.info(request, "No stale audit runs found.")
    return redirect("securityaudit:audit_jobs")


@permission_required("securityaudit.run_audit", raise_exception=True)
@require_http_methods(["GET", "POST"])
def run_audit(request):
    if request.method == "POST":
        form = AuditRunForm(request.POST)
        if form.is_valid():
            target_type = form.cleaned_data["target_type"]
            character_name = form.cleaned_data.get("character_name")
            character_id = form.cleaned_data.get("character_id")
            corporation_name = form.cleaned_data.get("corporation_name")
            corporation_id = form.cleaned_data.get("corporation_id")
            defaults = {}
            lookup = {"target_type": target_type}
            if target_type == AuditTarget.TARGET_INDIVIDUAL:
                if character_id:
                    lookup["character_id"] = character_id
                    defaults["character_name"] = character_name
                else:
                    lookup["character_name"] = character_name
            else:
                corp_id = corporation_id or EsiClient().resolve_corporation_name(corporation_name)
                if not corp_id:
                    form.add_error("corporation_name", "Corporation could not be resolved from ESI.")
                    return render(
                        request,
                        "securityaudit/run_audit.html",
                        {"form": form, "active_nav": "run_audit"},
                    )
                lookup["corp_id"] = corp_id
                defaults["corp_name"] = corporation_name

            target, _ = AuditTarget.objects.get_or_create(**lookup, defaults=defaults)
            if target_type == AuditTarget.TARGET_CORP and target.corp_name != corporation_name:
                target.corp_name = corporation_name
                target.save(update_fields=["corp_name"])

            existing_active = (
                AuditRun.objects.filter(
                    target=target,
                    status__in=[AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING],
                )
                .order_by("-created_at")
                .first()
            )
            if existing_active:
                messages.info(
                    request,
                    f"An audit for this target is already active (#{existing_active.id}). Redirected to existing run.",
                )
                return redirect("securityaudit:audit_detail", audit_id=existing_active.id)

            run = AuditRun.objects.create(
                target=target,
                status=AuditRun.STATUS_QUEUED,
                started_by=request.user,
                automated=False,
            )
            run.policy_overrides = form.cleaned_data.get("policy_overrides", {})
            run.save(update_fields=["policy_overrides"])
            result = enqueue_task(process_audit_run, run.id)
            run.task_id = getattr(result, "id", "")
            run.save(update_fields=["task_id"])
            messages.success(request, f"Queued audit run #{run.id}")
            return redirect("securityaudit:audit_detail", audit_id=run.id)
    else:
        form = AuditRunForm(initial={"target_type": AuditTarget.TARGET_INDIVIDUAL})

    return render(request, "securityaudit/run_audit.html", {"form": form, "active_nav": "run_audit"})


@login_required
@require_http_methods(["POST"])
def audit_rerun(request, audit_id):
    if not _is_admin(request.user) and not request.user.has_perm("securityaudit.run_audit"):
        return HttpResponseForbidden("Missing permission")
    run = get_object_or_404(AuditRun.objects.select_related("target"), pk=audit_id)
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")

    existing_active = (
        AuditRun.objects.filter(
            target=run.target,
            status__in=[AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING],
        )
        .order_by("-created_at")
        .first()
    )
    if existing_active:
        messages.info(
            request,
            f"An audit for this target is already active (#{existing_active.id}). Redirected to existing run.",
        )
        return redirect("securityaudit:audit_detail", audit_id=existing_active.id)

    new_run = AuditRun.objects.create(
        target=run.target,
        status=AuditRun.STATUS_QUEUED,
        started_by=request.user,
        automated=False,
    )
    result = enqueue_task(process_audit_run, new_run.id)
    new_run.task_id = getattr(result, "id", "")
    new_run.save(update_fields=["task_id"])
    messages.success(request, f"Queued rerun #{new_run.id} for target {run.target}.")
    return redirect("securityaudit:audit_detail", audit_id=new_run.id)


@login_required
@require_http_methods(["POST"])
def audit_requeue(request, audit_id):
    if not request.user.has_perm("securityaudit.run_audit"):
        return HttpResponseForbidden("Missing permission")
    run = get_object_or_404(AuditRun.objects.select_related("target"), pk=audit_id)
    if run.started_by != request.user:
        return HttpResponseForbidden("Missing permission")

    active_statuses = [AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]
    if run.status in active_statuses:
        messages.error(request, "Cannot re-queue an active audit.")
        return redirect("securityaudit:audit_detail", audit_id=run.id)
    if run.child_runs.filter(status__in=active_statuses).exists():
        messages.error(request, "Cannot re-queue an audit with active child runs.")
        return redirect("securityaudit:audit_detail", audit_id=run.id)

    run.reset_to_pending()
    children = list(run.child_runs.all())
    if children:
        for child in children:
            child.reset_to_pending()
            result = enqueue_task(process_audit_run, child.id)
            child.task_id = getattr(result, "id", "")
            child.save(update_fields=["task_id"])
    else:
        result = enqueue_task(process_audit_run, run.id)
        run.task_id = getattr(result, "id", "")
        run.save(update_fields=["task_id"])
    messages.success(request, f"Re-queued audit #{run.id}.")
    return redirect("securityaudit:audit_detail", audit_id=run.id)


@login_required
@require_http_methods(["POST"])
def audit_delete(request, audit_id):
    if not _is_admin(request.user) and not request.user.has_perm("securityaudit.run_audit"):
        return HttpResponseForbidden("Missing permission")
    run = get_object_or_404(AuditRun, pk=audit_id)
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")
    if run.status in [AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]:
        messages.error(request, "Cannot delete an audit that is queued or currently running.")
        return redirect("securityaudit:audit_detail", audit_id=run.id)

    run_id = run.id
    run.delete()
    messages.success(request, f"Deleted audit #{run_id}.")
    return redirect("securityaudit:dashboard")


@login_required
@require_http_methods(["POST"])
def audit_stop(request, audit_id):
    if not _is_admin(request.user) and not request.user.has_perm("securityaudit.run_audit"):
        return HttpResponseForbidden("Missing permission")
    run = get_object_or_404(AuditRun, pk=audit_id)
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")
    if run.status not in [AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]:
        messages.error(request, "Audit is not active.")
        return redirect("securityaudit:audit_detail", audit_id=run.id)
    if run.task_id and AsyncResult is not None:
        try:
            AsyncResult(run.task_id).revoke(terminate=True)
        except Exception:
            pass
    run.mark_failed("Stopped by user")
    _update_parent_run(run)
    messages.success(request, f"Stopped audit #{run.id}.")
    return redirect("securityaudit:audit_detail", audit_id=run.id)


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["POST"])
def audit_bulk_delete(request):
    run_ids = request.POST.getlist("run_ids")
    selected = []
    for value in run_ids:
        try:
            selected.append(int(value))
        except (TypeError, ValueError):
            continue

    if not selected:
        messages.info(request, "No audits selected.")
        return redirect("securityaudit:dashboard")

    queryset = AuditRun.objects.filter(id__in=selected)
    blocked_count = queryset.filter(status__in=[AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]).count()
    deletable = queryset.exclude(status__in=[AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING])
    deleted_count = deletable.count()
    if deleted_count:
        deletable.delete()

    if deleted_count:
        messages.success(request, f"Deleted {deleted_count} selected audit(s).")
    if blocked_count:
        messages.warning(request, f"Skipped {blocked_count} queued/running audit(s).")
    return redirect("securityaudit:dashboard")


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["POST"])
def audit_bulk_requeue(request):
    run_ids = request.POST.getlist("run_ids")
    selected = []
    for value in run_ids:
        try:
            selected.append(int(value))
        except (TypeError, ValueError):
            continue

    if not selected:
        messages.info(request, "No audits selected.")
        return redirect("securityaudit:dashboard")

    queryset = AuditRun.objects.filter(id__in=selected)
    active_statuses = [AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]
    skipped = list(queryset.filter(status__in=active_statuses))
    requeued_ids = []
    for run in queryset.exclude(status__in=active_statuses).select_related("target"):
        if run.child_runs.filter(status__in=active_statuses).exists():
            skipped.append(run)
            continue
        run.reset_to_pending()
        children = list(run.child_runs.all())
        if children:
            for child in children:
                child.reset_to_pending()
                result = enqueue_task(process_audit_run, child.id)
                child.task_id = getattr(result, "id", "")
                child.save(update_fields=["task_id"])
        else:
            result = enqueue_task(process_audit_run, run.id)
            run.task_id = getattr(result, "id", "")
            run.save(update_fields=["task_id"])
        requeued_ids.append(run.id)

    if requeued_ids:
        messages.success(request, f"Re-queued {len(requeued_ids)} selected audit(s).")
    if skipped:
        messages.warning(request, f"Skipped {len(skipped)} queued/running or parent-with-active-child audit(s).")
    return redirect("securityaudit:dashboard")


def _can_use_autocomplete(request):
    return request.user.has_perm("securityaudit.run_audit") or _is_admin(request.user)


def autocomplete_corporations(request):
    if not _can_use_autocomplete(request):
        return HttpResponseForbidden("Missing permission")
    query = request.GET.get("q", "")
    rows = MemberAuditAdapter.search_corporations(query, limit=12)
    return JsonResponse({"results": rows})


def autocomplete_characters(request):
    if not _can_use_autocomplete(request):
        return HttpResponseForbidden("Missing permission")
    query = request.GET.get("q", "")
    rows = MemberAuditAdapter.search_character_targets(query, limit=12)
    return JsonResponse({"results": rows})


@permission_required("securityaudit.view_dashboard", raise_exception=True)
def audit_progress(request, audit_id):
    run = get_object_or_404(AuditRun, pk=audit_id)
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")
    return JsonResponse(
        {
            "id": run.id,
            "status": run.status,
            "status_display": run.get_status_display(),
            "progress_current": run.progress_current,
            "progress_total": run.progress_total,
            "progress_percent": run.progress_percent,
            "progress_message": run.progress_message,
            "progress_details": run.progress_details,
            "risk_score": run.risk_score,
            "risk_level": run.risk_level,
            "summary": _corporation_summary(run),
            "missing_scopes": run.missing_scopes,
            "error_message": run.error_message,
            "finished": bool(run.finished_at),
        }
    )


def _target_affiliations(target):
    """Return dict with character/corp/alliance display, preferring local cached data."""
    cache_key = f"securityaudit:target_affiliations_v2:{target.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    esi = EsiClient()
    result = {
        "character_name": target.character_name or "",
        "character_id": target.character_id,
        "portrait_url": "",
        "corp_name": target.corp_name or "",
        "corp_id": target.corp_id,
        "corp_logo_url": "",
        "alliance_name": "",
        "alliance_id": None,
        "alliance_logo_url": "",
        "is_declared_alt": False,
    }

    snapshot = None
    if target.character_id:
        snapshot = MemberAuditAdapter.get_character_snapshot(character_id=target.character_id)

    if snapshot:
        if not result["character_name"]:
            result["character_name"] = snapshot.get("name") or ""
        if snapshot.get("corporation_id"):
            result["corp_id"] = snapshot["corporation_id"]
        if snapshot.get("alliance_id"):
            result["alliance_id"] = snapshot["alliance_id"]
    elif target.target_type == AuditTarget.TARGET_INDIVIDUAL and target.character_id:
        try:
            char = esi.get_character(target.character_id)
            result["character_name"] = char.get("name") or result["character_name"]
            result["corp_id"] = char.get("corporation_id") or result["corp_id"]
            result["alliance_id"] = char.get("alliance_id") or None
        except Exception:
            pass

    if target.character_id:
        result["portrait_url"] = MemberAuditAdapter._portrait_url(target.character_id)

    if result["corp_id"]:
        corp_id = result["corp_id"]
        result["corp_logo_url"] = MemberAuditAdapter._corp_logo_url(corp_id)
        corp_summaries = MemberAuditAdapter.get_corporation_summaries([corp_id])
        local_corp = (corp_summaries or [None])[0]
        local_name = (local_corp or {}).get("name") or ""
        if local_name and local_name != str(corp_id):
            result["corp_name"] = local_name
        elif not result["corp_name"] or result["corp_name"] == str(corp_id):
            try:
                names = esi.resolve_names([corp_id])
                resolved = names.get(corp_id)
                if resolved:
                    result["corp_name"] = resolved
            except Exception:
                pass

    if result["alliance_id"]:
        alliance_id = result["alliance_id"]
        result["alliance_logo_url"] = f"https://images.evetech.net/alliances/{alliance_id}/logo?size=64"
        try:
            names = esi.resolve_names([alliance_id])
            resolved = names.get(alliance_id)
            if resolved:
                result["alliance_name"] = resolved
        except Exception:
            pass

    cache.set(cache_key, result, 3600)
    return result


def _resolve_counterparty_entity(esi, entity_id):
    """Try ESI to identify whether an ID is a character, corporation, or alliance."""
    try:
        char = esi.get_character(entity_id)
        return {
            "kind": "character",
            "name": char.get("name") or "",
            "corp_id": char.get("corporation_id"),
            "alliance_id": char.get("alliance_id"),
        }
    except Exception:
        pass
    try:
        corp = esi.get_corporation(entity_id)
        return {
            "kind": "corporation",
            "name": corp.get("name") or "",
            "corp_id": entity_id,
            "alliance_id": corp.get("alliance_id"),
        }
    except Exception:
        pass
    try:
        alliance = esi.get_alliance(entity_id)
        return {
            "kind": "alliance",
            "name": alliance.get("name") or "",
            "corp_id": None,
            "alliance_id": entity_id,
        }
    except Exception:
        pass
    return None


def _counterparties_meta(run):
    """Enrich counterparties with portrait, name, corp, alliance, and alt status."""
    esi = EsiClient()
    counterparties = list(run.counterparties.all())
    if not counterparties:
        return [], set()

    target_user = None
    if run.target.target_type == AuditTarget.TARGET_INDIVIDUAL and run.target.character_id:
        target_user = MemberAuditAdapter.find_user_by_character_id(run.target.character_id)
    declared_ids = MemberAuditAdapter.get_user_declared_character_ids(target_user)

    to_resolve = set()
    base_data = {}
    for cp in counterparties:
        if cp.counterparty_type == AuditRelationshipCounterparty.COUNTERPARTY_ISK_DONATION:
            relationship = "Target sent ISK" if cp.is_outgoing else "Target received ISK"
        elif cp.counterparty_type == AuditRelationshipCounterparty.COUNTERPARTY_PLUS_TEN:
            relationship = "High-standing contact (+10)"
        elif cp.counterparty_type == AuditRelationshipCounterparty.COUNTERPARTY_FREE_CONTRACT:
            relationship = "Free contract interaction"
        elif cp.counterparty_type == AuditRelationshipCounterparty.COUNTERPARTY_POSSIBLE_ALT:
            relationship = "Possible alt via corp history"
        else:
            relationship = "Observed counterparty"

        base_data[cp.id] = {
            "portrait_url": "",
            "character_name": cp.character_name or "",
            "character_id": cp.character_id,
            "corp_name": "",
            "alliance_name": "",
            "is_declared_alt": (cp.character_id in declared_ids) if cp.character_id else False,
            "type": cp.get_counterparty_type_display(),
            "relationship": relationship,
            "total_amount": cp.total_amount,
            "is_outgoing": cp.is_outgoing,
            "event_count": cp.event_count,
            "notes": cp.notes or "",
        }
        if not cp.character_id:
            continue

        # Prefer locally cached data when available
        snapshot = MemberAuditAdapter.get_character_snapshot(character_id=cp.character_id)
        if snapshot:
            if not base_data[cp.id]["character_name"]:
                base_data[cp.id]["character_name"] = snapshot.get("name") or ""
            base_data[cp.id]["portrait_url"] = MemberAuditAdapter._portrait_url(cp.character_id)
            corp_id = snapshot.get("corporation_id")
            alliance_id = snapshot.get("alliance_id")
        else:
            entity = _resolve_counterparty_entity(esi, cp.character_id)
            if entity:
                if not base_data[cp.id]["character_name"]:
                    base_data[cp.id]["character_name"] = entity.get("name") or ""
                kind = entity.get("kind")
                if kind == "character":
                    base_data[cp.id]["portrait_url"] = MemberAuditAdapter._portrait_url(cp.character_id)
                elif kind == "corporation":
                    base_data[cp.id]["portrait_url"] = MemberAuditAdapter._corp_logo_url(cp.character_id)
                elif kind == "alliance":
                    base_data[cp.id]["portrait_url"] = MemberAuditAdapter._alliance_logo_url(cp.character_id)
                corp_id = entity.get("corp_id")
                alliance_id = entity.get("alliance_id")
            else:
                base_data[cp.id]["portrait_url"] = MemberAuditAdapter._portrait_url(cp.character_id)
                corp_id = None
                alliance_id = None

        if corp_id:
            to_resolve.add(corp_id)
        if alliance_id:
            to_resolve.add(alliance_id)

        # Cache per-cp ids for name resolution
        base_data[cp.id]["_corp_id"] = corp_id
        base_data[cp.id]["_alliance_id"] = alliance_id

    resolved = esi.resolve_names(to_resolve) if to_resolve else {}
    for cp in counterparties:
        cp_id = cp.id
        corp_id = base_data[cp_id].pop("_corp_id", None)
        alliance_id = base_data[cp_id].pop("_alliance_id", None)
        base_data[cp_id]["corp_name"] = resolved.get(corp_id) or ""
        base_data[cp_id]["alliance_name"] = resolved.get(alliance_id) or ""

    memberaudit_url_map = {}
    ma_model = MemberAuditAdapter._get_model("memberaudit", "Character")
    if ma_model:
        eve_ids = {cp.character_id for cp in counterparties if cp.character_id}
        ma_pks = {
            obj.eve_character_id: obj.pk
            for obj in ma_model.objects.filter(eve_character_id__in=eve_ids).only("eve_character_id", "pk")
        }
        for cp in counterparties:
            if cp.character_id in ma_pks:
                try:
                    memberaudit_url_map[cp.id] = reverse(
                        "memberaudit:character_viewer",
                        kwargs={"character_pk": ma_pks[cp.character_id]},
                    )
                except Exception:
                    pass

    for cp in counterparties:
        cp_id = cp.id
        base_data[cp_id]["zkill_url"] = f"https://zkillboard.com/character/{cp.character_id}/" if cp.character_id else ""
        base_data[cp_id]["memberaudit_url"] = memberaudit_url_map.get(cp_id, "")

    return list(base_data.values()), declared_ids


def _prepare_finding_evidence(findings):
    for finding in findings:
        prepared = []
        for item in finding.evidence.all():
            item.collusion_killmail_links = []
            item.matched_entities = []
            item.awox_kill_links = []

            if item.key == "collusion_killmail_ids":
                raw_value = str(item.value or "").strip()
                entries = []
                if raw_value:
                    try:
                        parsed = json.loads(raw_value)
                        if isinstance(parsed, list):
                            entries = parsed
                    except Exception:
                        entries = [
                            {"killmail_id": token.strip(), "date": "unknown date"}
                            for token in raw_value.split(",")
                            if token.strip().isdigit()
                        ]

                known = [e for e in entries if e.get("date") != "unknown date"]
                unknown = [e for e in entries if e.get("date") == "unknown date"]
                known.sort(key=lambda e: e.get("date", ""), reverse=True)
                item.collusion_killmail_links = [
                    {
                        "date": e.get("date", "unknown date"),
                        "url": f"https://zkillboard.com/kill/{e.get('killmail_id')}/",
                        "matches": e.get("matches", []),
                    }
                    for e in (known + unknown)[:20]
                ]
            elif item.key == "matched_enemy_or_blacklist_entities":
                entities = []
                raw_value = str(item.value or "").strip()
                if raw_value:
                    try:
                        parsed = json.loads(raw_value)
                        if isinstance(parsed, list):
                            entities = parsed
                    except Exception:
                        entities = []

                normalized_entities = []
                for entity in entities:
                    if not isinstance(entity, dict):
                        continue
                    entity_type = str(entity.get("entity_type") or "")
                    source = str(entity.get("source") or "enemy")
                    entity_id = entity.get("entity_id")
                    try:
                        entity_id = int(entity_id)
                    except (TypeError, ValueError):
                        continue

                    image_url = entity.get("image_url") or ""
                    if not image_url:
                        if entity_type == "character":
                            image_url = MemberAuditAdapter._portrait_url(entity_id)
                        elif entity_type == "corporation":
                            image_url = MemberAuditAdapter._corp_logo_url(entity_id)
                        elif entity_type == "alliance":
                            image_url = MemberAuditAdapter._alliance_logo_url(entity_id)

                    normalized_entities.append(
                        {
                            "source": source,
                            "entity_type": entity_type,
                            "entity_id": entity_id,
                            "name": entity.get("name") or str(entity_id),
                            "image_url": image_url,
                        }
                    )

                item.matched_entities = normalized_entities
            elif item.key == "awox_killmails":
                raw_value = str(item.value or "").strip()
                entries = []
                if raw_value:
                    try:
                        parsed = json.loads(raw_value)
                        if isinstance(parsed, list):
                            entries = parsed
                    except Exception:
                        entries = []

                from .services.audit_analysis.awox import KIND_LABELS

                kill_links = []
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    kind = str(e.get("kind") or "")
                    victim = e.get("victim") or {}
                    audited = e.get("audited_char") or {}
                    contributors = e.get("audited_contributors") or []
                    if not isinstance(contributors, list):
                        contributors = []
                    kill_links.append({
                        "date": e.get("date", "unknown date"),
                        "zkill_url": e.get("zkill_url") or (
                            f"https://zkillboard.com/kill/{e.get('killmail_id')}/"
                            if e.get("killmail_id") else ""
                        ),
                        "kind": kind,
                        "kind_label": KIND_LABELS.get(kind, kind),
                        "friendly_path": e.get("friendly_path") or "",
                        "friendly_link_char_name": e.get("friendly_link_char_name") or "",
                        "friendly_link_type": e.get("friendly_link_type") or "",
                        "victim_name": victim.get("character_name") or "",
                        "victim_image_url": victim.get("image_url") or "",
                        "victim_ship_name": victim.get("ship_name") or "",
                        "victim_ship_type_id": victim.get("ship_type_id") or "",
                        "zkb_value": e.get("zkb_value") or 0,
                        "damage_share_pct": float(e.get("damage_share") or 0) * 100.0,
                        "final_blow": bool(e.get("final_blow")),
                        "attacker_count": e.get("attacker_count") or 0,
                        "audited_char_name": audited.get("character_name") or "",
                        "audited_contributors": contributors,
                        "weapon_name": e.get("weapon_name") or "",
                        "enemy_attackers_present": bool(e.get("enemy_attackers_present")),
                        "kill_score": e.get("kill_score") or 0,
                    })
                kill_links.sort(key=lambda x: x["date"], reverse=True)
                item.awox_kill_links = kill_links[:20]
            elif item.key == "enemy_connection":
                raw_value = str(item.value or "").strip()
                if raw_value:
                    try:
                        item.enemy_connection = json.loads(raw_value)
                    except Exception:
                        item.enemy_connection = {}
                else:
                    item.enemy_connection = {}

            prepared.append(item)

        finding.prepared_evidence = prepared


def _character_corp_history(target, limit=None):
    """Return sorted character corp history rows with names, logos, NPC flags, durations, end dates, and hop windows."""
    if target.target_type != AuditTarget.TARGET_INDIVIDUAL or not target.character_id:
        return []

    history = MemberAuditAdapter.get_character_corp_history(character_id=target.character_id)
    if not history:
        try:
            history = EsiClient().get_character_corp_history(target.character_id)
        except Exception:
            history = []

    if not history:
        return []

    policy = AuditPolicy.get_solo()
    window_start = timezone.now() - timedelta(days=policy.corp_hop_window_days)
    window_timedelta = timedelta(days=policy.corp_hop_window_days)
    esi = EsiClient()

    corp_ids = set()
    parsed = []
    for row in history:
        corp_id = row.get("corporation_id")
        start_date = None
        if row.get("start_date"):
            try:
                start_date = timezone.datetime.fromisoformat(row["start_date"].replace("Z", "+00:00"))
            except ValueError:
                start_date = EsiClient.parse_esi_time(row["start_date"])
        if corp_id:
            corp_ids.add(corp_id)
        parsed.append(
            {
                "corporation_id": corp_id,
                "start_date": start_date,
                "start_date_str": row.get("start_date") or "",
                "in_window": bool(start_date and start_date >= window_start),
            }
        )

    names = esi.resolve_names(corp_ids)

    cache_key = "securityaudit:npc_corp_ids"
    npc_ids = cache.get(cache_key)
    if npc_ids is None:
        try:
            npc_ids = set(esi.get_npc_corporations())
        except Exception:
            npc_ids = set()
        cache.set(cache_key, npc_ids, 86400)

    for item in parsed:
        corp_id = item["corporation_id"]
        item["corp_name"] = names.get(corp_id) or str(corp_id or "Unknown")
        item["logo_url"] = MemberAuditAdapter._corp_logo_url(corp_id)
        item["npc"] = corp_id in npc_ids

    # Rows without a usable date are preserved for display but cannot be part of windows/durations.
    dated = [p for p in parsed if p["start_date"] is not None]
    dated.sort(key=lambda x: x["start_date"])
    undated = [p for p in parsed if p["start_date"] is None]

    now = timezone.now()
    n = len(dated)
    for i, row in enumerate(dated):
        is_current = i == n - 1
        end_date = now if is_current else dated[i + 1]["start_date"]
        row["end_date"] = end_date
        row["end_date_str"] = "Present" if is_current else end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        row["duration_days"] = (end_date - row["start_date"]).days
        row["is_hop"] = False

    for p in undated:
        p["end_date"] = None
        p["end_date_str"] = ""
        p["duration_days"] = None
        p["is_hop"] = False

    # Mark every row that belongs to at least one hop window of size window_days
    # with >= threshold changes. NPC corporation memberships are excluded from
    # the hop calculation (they don't count toward the threshold and are never
    # marked as hop rows).
    hop_dated = [p for p in dated if not p["npc"]]
    hn = len(hop_dated)
    j = 0
    for i in range(hn):
        while j < hn and (hop_dated[j]["start_date"] - hop_dated[i]["start_date"]) <= window_timedelta:
            j += 1
        if (j - i) >= policy.corp_hop_count_threshold:
            for k in range(i, j):
                hop_dated[k]["is_hop"] = True

    rows = dated + undated
    min_dt = timezone.make_aware(timezone.datetime.min)
    rows.sort(key=lambda x: (x["start_date"] or min_dt, x["end_date"] or min_dt), reverse=True)
    return rows[:limit]


def _capital_ship_observations(run):
    """Group capital ship observations by category for display."""
    from .services.audit_analysis.capital_ships import CATEGORY_ORDER, CATEGORY_LABELS, ship_image_url

    qs = run.capital_ship_observations.all()
    if not qs:
        return []

    by_cat = {}
    for obs in qs:
        cat = obs.ship_category
        ship = by_cat.setdefault(cat, {}).setdefault(
            obs.ship_type_id,
            {
                "ship_type_id": obs.ship_type_id,
                "ship_name": obs.ship_name,
                "image_url": ship_image_url(obs.ship_type_id),
                "zkill_url": f"https://zkillboard.com/ship/{obs.ship_type_id}/",
                "characters": [],
                "total_asset_count": 0,
                "total_contract_count": 0,
                "total_owned_count": 0,
            },
        )
        ship["characters"].append(
            {
                "character_id": obs.character_id,
                "character_name": obs.character_name or str(obs.character_id),
                "observation_count": obs.observation_count,
                "first_seen": obs.first_seen,
                "last_seen": obs.last_seen,
                "asset_count": obs.asset_count,
                "is_current_ship": obs.is_current_ship,
                "contract_count": obs.contract_count,
                "market_order_count": obs.market_order_count,
            }
        )
        ship["total_asset_count"] += obs.asset_count
        ship["total_contract_count"] += int(obs.contract_count or 0)
        ship["total_owned_count"] += int(obs.asset_count or 0) + int(obs.contract_count or 0)

    result = []
    for cat in CATEGORY_ORDER:
        ships = by_cat.get(cat)
        if not ships:
            continue
        ship_list = sorted(ships.values(), key=lambda s: s["ship_name"])
        for s in ship_list:
            s["characters"].sort(key=lambda c: c["character_name"])
            # Build tooltip text for the combined ownership overlay badge.
            ownership_parts = []
            for c in s["characters"]:
                asset_count = int(c.get("asset_count") or 0)
                contract_count = int(c.get("contract_count") or 0)
                if not asset_count and not contract_count and not c.get("is_current_ship"):
                    continue
                label = c["character_name"]
                detail = f"assets: {asset_count}, contracts: {contract_count}"
                if c.get("is_current_ship"):
                    detail += ", active ship"
                ownership_parts.append(f"{label} ({detail})")
            if ownership_parts:
                s["ownership_tooltip"] = (
                    f"{s['total_owned_count']} total (assets + contract hulls): "
                    + "; ".join(ownership_parts)
                )
            else:
                s["ownership_tooltip"] = ""
        total_obs = sum(c["observation_count"] for s in ship_list for c in s["characters"])
        total_owned = sum(s["total_owned_count"] for s in ship_list)
        result.append(
            {
                "category": cat,
                "label": CATEGORY_LABELS.get(cat, cat.title()),
                "ships": ship_list,
                "total_observations": total_obs,
                "total_owned_count": total_owned,
            }
        )
    return result


def _dashboard_target_meta(audit_runs):
    """Enrich dashboard rows with portrait, corp/alliance logos, and MemberAudit links."""
    targets = [run.target for run in audit_runs if run.target]
    meta = {}

    character_ids = set()
    corp_ids = set()
    for target in targets:
        if target.target_type == AuditTarget.TARGET_INDIVIDUAL and target.character_id:
            character_ids.add(target.character_id)
        if target.corp_id:
            corp_ids.add(target.corp_id)

    eve_char_map = {}
    EveCharacter = MemberAuditAdapter._get_model("eveonline", "EveCharacter")
    if EveCharacter and character_ids:
        try:
            for obj in EveCharacter.objects.filter(character_id__in=character_ids).only(
                "character_id", "character_name", "corporation_id", "alliance_id"
            ):
                eve_char_map[obj.character_id] = obj
        except Exception:
            pass

    memberaudit_url_map = {}
    ma_model = MemberAuditAdapter._get_model("memberaudit", "Character")
    if ma_model and character_ids:
        try:
            for obj in ma_model.objects.filter(eve_character_id__in=character_ids).only("pk", "eve_character_id"):
                try:
                    memberaudit_url_map[obj.eve_character_id] = reverse(
                        "memberaudit:character_viewer", kwargs={"character_pk": obj.pk}
                    )
                except Exception:
                    pass
        except Exception:
            pass

    ids_to_resolve = set(corp_ids) | set(character_ids)
    for obj in eve_char_map.values():
        if obj.corporation_id:
            ids_to_resolve.add(obj.corporation_id)
        if obj.alliance_id:
            ids_to_resolve.add(obj.alliance_id)

    names = EsiClient().resolve_names(ids_to_resolve) if ids_to_resolve else {}

    for target in targets:
        is_individual = target.target_type == AuditTarget.TARGET_INDIVIDUAL
        item = {
            "target_type": target.target_type,
            "portrait_url": "",
            "memberaudit_url": "",
            "display_name": "",
            "corp_id": target.corp_id,
            "corp_name": "",
            "corp_logo_url": "",
            "alliance_id": None,
            "alliance_name": "",
            "alliance_logo_url": "",
        }

        if is_individual:
            item["portrait_url"] = MemberAuditAdapter._portrait_url(target.character_id)
            item["memberaudit_url"] = memberaudit_url_map.get(target.character_id, "")
            item["display_name"] = target.character_name or names.get(target.character_id) or str(target.character_id)
            eve_obj = eve_char_map.get(target.character_id)
            if eve_obj:
                if eve_obj.character_name and not target.character_name:
                    item["display_name"] = eve_obj.character_name
                if eve_obj.corporation_id:
                    item["corp_id"] = eve_obj.corporation_id
                if eve_obj.alliance_id:
                    item["alliance_id"] = eve_obj.alliance_id
        else:
            item["display_name"] = target.corp_name or names.get(target.corp_id) or str(target.corp_id)
            item["corp_id"] = target.corp_id
            if target.corp_id:
                item["portrait_url"] = MemberAuditAdapter._corp_logo_url(target.corp_id)

        if item["corp_id"]:
            item["corp_name"] = names.get(item["corp_id"]) or target.corp_name or str(item["corp_id"])
            item["corp_logo_url"] = MemberAuditAdapter._corp_logo_url(item["corp_id"])
        if item["alliance_id"]:
            item["alliance_name"] = names.get(item["alliance_id"]) or str(item["alliance_id"])
            item["alliance_logo_url"] = MemberAuditAdapter._alliance_logo_url(item["alliance_id"])

        meta[target.pk] = item

    return meta


@permission_required("securityaudit.view_dashboard", raise_exception=True)
def audit_detail(request, audit_id):
    run = get_object_or_404(
        AuditRun.objects.select_related("target").prefetch_related(
            "findings__evidence", "counterparties", "child_runs__target"
        ),
        pk=audit_id,
    )
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")
    AuditSummaryView.objects.get_or_create(audit_run=run, user=request.user)

    summary_path = reverse("securityaudit:audit_summary", kwargs={"audit_id": run.id})
    can_view_summary = _is_admin(request.user) or request.user.has_perm("securityaudit.view_summaries") or _can_view_run(request.user, run)
    can_generate_link = _can_view_run(request.user, run) and (_is_admin(request.user) or request.user.has_perm("securityaudit.generate_link"))
    can_rerun = _is_admin(request.user) or (request.user.has_perm("securityaudit.run_audit") and _can_view_run(request.user, run))
    can_requeue = request.user.has_perm("securityaudit.run_audit") and run.started_by == request.user
    can_delete = _is_admin(request.user) or (request.user.has_perm("securityaudit.run_audit") and _can_view_run(request.user, run))
    can_stop = (
        (_is_admin(request.user) or (request.user.has_perm("securityaudit.run_audit") and _can_view_run(request.user, run)))
        and run.status in [AuditRun.STATUS_QUEUED, AuditRun.STATUS_RUNNING]
    )
    summary_url = request.build_absolute_uri(summary_path) if can_view_summary else ""
    summary_views = []
    if can_view_summary:
        for view in run.summary_views.select_related("user").order_by("-viewed_at"):
            portrait, character_name = _initiator_display(view.user)
            summary_views.append(
                {
                    "portrait_url": portrait,
                    "character_name": character_name,
                    "viewed_at": view.viewed_at,
                }
            )

    generated_link_url = ""
    generated_token = request.GET.get("token", "")
    if generated_token:
        link = _get_valid_summary_link(run, generated_token)
        if link:
            generated_link_url = request.build_absolute_uri(
                f"{summary_path}?token={link.token}"
            )

    started_by_portrait, started_by_name = _initiator_display(run.started_by)

    findings = list(run.findings.all())
    _prepare_finding_evidence(findings)
    counterparty_rows, _ = _counterparties_meta(run)
    counterparty_by_id = {str(row["character_id"]): row for row in counterparty_rows}
    policy = AuditPolicy.get_solo()
    return render(
        request,
        "securityaudit/audit_detail.html",
        {
            "run": run,
            "findings": findings,
            "active_nav": "dashboard",
            "can_view_summary": can_view_summary,
            "can_generate_link": can_generate_link,
            "can_rerun": can_rerun,
            "can_requeue": can_requeue,
            "can_delete": can_delete,
            "can_stop": can_stop,
            "summary_url": summary_url,
            "generated_link_url": generated_link_url,
            "summary_views": summary_views,
            "started_by_portrait": started_by_portrait,
            "started_by_name": started_by_name,
            "disclosed_alts": _disclosed_alts(run.target, run=run, include_target=True),
            "target_affiliations": _target_affiliations(run.target),
            "counterparty_rows": counterparty_rows,
            "counterparty_by_id": counterparty_by_id,
            "corp_history": _character_corp_history(run.target),
            "corp_hop_window_days": policy.corp_hop_window_days,
            "corp_hop_count_threshold": policy.corp_hop_count_threshold,
            "summary_link_expiry_hours": policy.summary_link_expiry_hours,
            "child_runs": _child_audit_rows(run, detail=True),
            "summary_text": _corporation_summary(run),
            "capital_ship_observations": _capital_ship_observations(run),
        },
    )


@login_required
def audit_summary(request, audit_id):
    run = get_object_or_404(
        AuditRun.objects.select_related("target").prefetch_related(
            "findings__evidence", "counterparties", "child_runs__target"
        ),
        pk=audit_id,
    )
    token = request.GET.get("token", "").strip()
    link = _get_valid_summary_link(run, token)
    if not link and not _is_admin(request.user) and not request.user.has_perm("securityaudit.view_summaries") and not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")
    AuditSummaryView.objects.get_or_create(audit_run=run, user=request.user)
    started_by_portrait, started_by_name = _initiator_display(run.started_by)
    findings = list(run.findings.all())
    _prepare_finding_evidence(findings)
    severity_breakdown = Counter(item.severity for item in findings)
    counterparty_rows, _ = _counterparties_meta(run)
    counterparty_by_id = {str(row["character_id"]): row for row in counterparty_rows}
    policy = AuditPolicy.get_solo()
    return render(
        request,
        "securityaudit/summary.html",
        {
            "run": run,
            "findings": findings,
            "started_by_portrait": started_by_portrait,
            "started_by_name": started_by_name,
            "severity_breakdown": severity_breakdown,
            "target_affiliations": _target_affiliations(run.target),
            "disclosed_alts": _disclosed_alts(run.target),
            "counterparty_rows": counterparty_rows,
            "counterparty_by_id": counterparty_by_id,
            "child_runs": _child_audit_rows(run, detail=False),
            "corp_history": _character_corp_history(run.target),
            "corp_hop_window_days": policy.corp_hop_window_days,
            "corp_hop_count_threshold": policy.corp_hop_count_threshold,
            "capital_ship_observations": _capital_ship_observations(run),
        },
    )


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["GET", "POST"])
def policy_edit(request):
    policy = AuditPolicy.get_solo()
    if request.method == "POST":
        form = AuditPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            messages.success(request, "Audit policy updated.")
            return redirect("securityaudit:policy_edit")
    else:
        form = AuditPolicyForm(instance=policy)
    return render(
        request,
        "securityaudit/policy_edit.html",
        {
            "form": form,
            "policy": policy,
            "active_nav": "policy",
        },
    )


@permission_required("securityaudit.view_enemies", raise_exception=True)
def enemy_list(request):
    rows = list(EnemyEntity.objects.order_by("entity_type", "entity_id"))
    ids = [r.entity_id for r in rows if r.entity_id]
    enemy_names = {}
    if ids:
        try:
            enemy_names = EsiClient().resolve_names(set(ids))
        except Exception:
            enemy_names = {}
    return render(
        request,
        "securityaudit/enemy_list.html",
        {
            "rows": rows,
            "active_nav": "enemies",
            "enemy_names": enemy_names,
        },
    )


@permission_required("securityaudit.manage_enemies", raise_exception=True)
@require_http_methods(["GET", "POST"])
def enemy_add(request):
    if request.method == "POST":
        form = EnemyEntityForm(request.POST)
        if form.is_valid():
            row = form.save(commit=False)
            row.created_by = request.user
            row.save()
            messages.success(request, "Enemy entity entry created.")
            return redirect("securityaudit:enemy_list")
    else:
        form = EnemyEntityForm()
    return render(request, "securityaudit/enemy_add.html", {"form": form, "active_nav": "enemies"})


@permission_required("securityaudit.manage_enemies", raise_exception=True)
@require_http_methods(["POST"])
def enemy_delete(request, enemy_id):
    row = get_object_or_404(EnemyEntity, pk=enemy_id)
    row.delete()
    messages.success(request, "Enemy entry deleted.")
    return redirect("securityaudit:enemy_list")


@permission_required("securityaudit.administrate", raise_exception=True)
def financial_exception_list(request):
    rows = list(FinancialException.objects.order_by("entity_type", "entity_id"))
    ids = [r.entity_id for r in rows if r.entity_id]
    exception_names = {}
    if ids:
        try:
            exception_names = EsiClient().resolve_names(set(ids))
        except Exception:
            exception_names = {}
    return render(
        request,
        "securityaudit/financial_exception_list.html",
        {
            "rows": rows,
            "active_nav": "exceptions",
            "exception_names": exception_names,
            "form": FinancialExceptionForm(),
        },
    )


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["GET", "POST"])
def financial_exception_add(request):
    if request.method == "POST":
        form = FinancialExceptionForm(request.POST)
        if form.is_valid():
            row = form.save(commit=False)
            row.created_by = request.user
            row.save()
            messages.success(request, "Financial exception created.")
            return redirect("securityaudit:financial_exception_list")
    else:
        form = FinancialExceptionForm()
    return render(request, "securityaudit/financial_exception_add.html", {"form": form, "active_nav": "exceptions"})


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["POST"])
def financial_exception_delete(request, exception_id):
    row = get_object_or_404(FinancialException, pk=exception_id)
    row.delete()
    messages.success(request, "Financial exception deleted.")
    return redirect("securityaudit:financial_exception_list")


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["GET", "POST"])
def financial_exception_edit(request, exception_id):
    row = get_object_or_404(FinancialException, pk=exception_id)
    if request.method == "POST":
        form = FinancialExceptionForm(request.POST, instance=row)
        if form.is_valid():
            form.save()
            messages.success(request, "Financial exception updated.")
            return redirect("securityaudit:financial_exception_list")
    else:
        form = FinancialExceptionForm(instance=row)
    return render(request, "securityaudit/financial_exception_edit.html", {"form": form, "row": row, "active_nav": "exceptions"})


@permission_required("securityaudit.manage_enemies", raise_exception=True)
@require_http_methods(["GET"])
def enemy_autocomplete(request):
    term = request.GET.get("q", "").strip()
    esi = EsiClient()

    def _character_affiliations(entity_id):
        try:
            char = esi.get_character(entity_id)
            corp_id = char.get("corporation_id")
            alliance_id = char.get("alliance_id")
            names = esi.resolve_names([v for v in (corp_id, alliance_id) if v])
            return names.get(corp_id) or "", names.get(alliance_id) or ""
        except Exception:
            return "", ""

    results = [
        item for item in MemberAuditAdapter.search_entities(term, limit=20, allowed_types=("corporation", "alliance"))
        if item.get("type") in ("corporation", "alliance")
    ]
    if term:
        enriched = []
        for item in results:
            row = dict(item)
            if row.get("type") == "character" and row.get("id"):
                corp_name, alliance_name = _character_affiliations(row["id"])
                row["corp_name"] = corp_name
                row["alliance_name"] = alliance_name
            enriched.append(row)
        results = enriched

    if term:
        try:
            existing = {(str(item.get("type")), int(item.get("id"))) for item in results if item.get("id") and item.get("type")}
            search_hits = esi.search_universe(term, strict=False)
            ids_to_resolve = []
            typed_ids = []

            for category, entity_type in (("corporations", "corporation"), ("alliances", "alliance")):
                for entity_id in search_hits.get(category, [])[:20]:
                    try:
                        entity_id = int(entity_id)
                    except (TypeError, ValueError):
                        continue
                    key = (entity_type, entity_id)
                    if key in existing:
                        continue
                    existing.add(key)
                    typed_ids.append((entity_type, entity_id))
                    ids_to_resolve.append(entity_id)

            resolved_names = esi.resolve_names(ids_to_resolve)
            for entity_type, entity_id in typed_ids:
                entity_name = resolved_names.get(entity_id)
                if not entity_name:
                    continue
                if entity_type == "character":
                    image_url = MemberAuditAdapter._portrait_url(entity_id)
                elif entity_type == "corporation":
                    image_url = MemberAuditAdapter._corp_logo_url(entity_id)
                elif entity_type == "alliance":
                    image_url = MemberAuditAdapter._alliance_logo_url(entity_id)
                else:
                    image_url = ""
                row = {
                    "id": entity_id,
                    "name": entity_name,
                    "type": entity_type,
                    "image_url": image_url,
                }
                if entity_type == "character":
                    row["corp_name"], row["alliance_name"] = _character_affiliations(entity_id)
                results.append(row)

            if not results:
                for item in esi.resolve_names_to_ids([term]):
                    entity_type = item.get("type")
                    entity_id = item.get("id")
                    entity_name = item.get("name")
                    if entity_type == "character" or not entity_type or not entity_id or not entity_name:
                        continue
                    key = (str(entity_type), int(entity_id))
                    if key in existing:
                        continue
                    existing.add(key)

                    if entity_type == "character":
                        image_url = MemberAuditAdapter._portrait_url(entity_id)
                    elif entity_type == "corporation":
                        image_url = MemberAuditAdapter._corp_logo_url(entity_id)
                    elif entity_type == "alliance":
                        image_url = MemberAuditAdapter._alliance_logo_url(entity_id)
                    else:
                        image_url = ""

                    row = {
                        "id": entity_id,
                        "name": entity_name,
                        "type": entity_type,
                        "image_url": image_url,
                    }
                    if entity_type == "character":
                        row["corp_name"], row["alliance_name"] = _character_affiliations(entity_id)
                    results.append(row)
        except Exception:
            pass
    grouped = {"corporation": [], "alliance": []}
    for item in results:
        grouped.setdefault(item.get("type"), []).append(item)

    mixed = []
    while len(mixed) < 20:
        added = False
        for entity_type in ("corporation", "alliance"):
            bucket = grouped.get(entity_type) or []
            if not bucket:
                continue
            mixed.append(bucket.pop(0))
            added = True
            if len(mixed) >= 20:
                break
        if not added:
            break

    return JsonResponse({"results": mixed})


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["GET"])
def financial_exception_autocomplete(request):
    term = request.GET.get("q", "").strip()
    esi = EsiClient()

    def _character_affiliations(entity_id):
        try:
            char = esi.get_character(entity_id)
            corp_id = char.get("corporation_id")
            alliance_id = char.get("alliance_id")
            names = esi.resolve_names([v for v in (corp_id, alliance_id) if v])
            return names.get(corp_id) or "", names.get(alliance_id) or ""
        except Exception:
            return "", ""

    results = []
    if term:
        for item in MemberAuditAdapter.search_entities(term, limit=20, allowed_types=("character", "corporation")):
            row = dict(item)
            if row.get("type") == "character" and row.get("id"):
                row["corp_name"], row["alliance_name"] = _character_affiliations(row["id"])
            results.append(row)

    grouped = {"character": [], "corporation": []}
    for item in results:
        grouped.setdefault(item.get("type"), []).append(item)

    mixed = []
    for _ in range(20):
        added = False
        for entity_type in ("character", "corporation"):
            bucket = grouped.get(entity_type) or []
            if bucket:
                mixed.append(bucket.pop(0))
                added = True
        if not added:
            break

    return JsonResponse({"results": mixed})


@permission_required("securityaudit.administrate", raise_exception=True)
@require_http_methods(["POST"])
def run_new_join_job(request):
    policy = AuditPolicy.get_solo()
    if not policy.enabled:
        return HttpResponseForbidden("Audit policy is disabled")
    enqueue_task(process_new_joins)
    messages.success(request, "Scheduled new-join processing job.")
    return redirect("securityaudit:dashboard")


@login_required
@require_http_methods(["POST"])
def generate_summary_link(request, audit_id):
    if not _is_admin(request.user) and not request.user.has_perm("securityaudit.generate_link"):
        return HttpResponseForbidden("Missing permission")
    run = get_object_or_404(AuditRun, pk=audit_id)
    if not _can_view_run(request.user, run):
        return HttpResponseForbidden("Missing permission")

    policy = AuditPolicy.get_solo()
    expires_at = None
    if policy.summary_link_expiry_hours:
        expires_at = timezone.now() + timedelta(hours=policy.summary_link_expiry_hours)

    link = AuditSummaryLink.objects.create(
        audit_run=run,
        created_by=request.user,
        expires_at=expires_at,
    )
    detail_url = reverse("securityaudit:audit_detail", kwargs={"audit_id": run.id})
    return redirect(f"{detail_url}?token={link.token}")


@login_required
def debug_permissions(request):
    from django.contrib.auth.models import Permission

    app_label = "securityaudit"
    all_perms = Permission.objects.filter(content_type__app_label=app_label).select_related("content_type")
    permissions = [
        {
            "codename": p.codename,
            "name": p.name,
            "has": request.user.has_perm(f"{app_label}.{p.codename}"),
        }
        for p in all_perms.order_by("codename")
    ]
    effective_perms = sorted(
        p for p in request.user.get_all_permissions() if p.startswith(f"{app_label}.")
    )

    profile = getattr(request.user, "profile", None)
    main = getattr(profile, "main_character", None)
    main_id = MemberAuditAdapter._extract_int(main, "character_id", "id") if main else None
    main_corp_id = MemberAuditAdapter._extract_int(main, "corporation_id", "corp_id", "corporation") if main else None

    declared_corps = []
    for character_id in MemberAuditAdapter.get_user_declared_character_ids(request.user):
        snapshot = MemberAuditAdapter.get_character_snapshot(character_id=character_id)
        if not snapshot:
            continue
        declared_corps.append({
            "id": snapshot.get("character_id"),
            "name": snapshot.get("name"),
            "corp_id": snapshot.get("corporation_id"),
        })

    context = {
        "permissions": permissions,
        "effective_perms": effective_perms,
        "is_superuser": request.user.is_superuser,
        "is_staff": request.user.is_staff,
        "main_id": main_id,
        "main_name": getattr(main, "character_name", None),
        "main_corp_id": main_corp_id,
        "declared_corps": declared_corps,
    }
    return render(request, "securityaudit/debug_permissions.html", context)


@login_required
def debug_audit_visibility(request, audit_id):
    run = get_object_or_404(
        AuditRun.objects.select_related("target", "started_by", "parent_run__target"),
        pk=audit_id,
    )
    if not _is_admin(request.user) and not _can_view_run(request.user, run):
        return HttpResponseForbidden("You cannot view this audit.")

    user = request.user
    is_admin = _is_admin(user)
    user_corp_ids = _user_declared_corp_ids(user)
    started_by = getattr(run, "started_by", None)
    started_by_match = bool(started_by and started_by == user)
    automated_match = run.automated

    target = getattr(run, "target", None)
    target_corp_id = None
    target_corp_name = None
    target_corp_match = False
    if target and target.target_type == AuditTarget.TARGET_CORP:
        target_corp_id = target.corp_id
        target_corp_name = target.corp_name
        if not is_admin:
            target_corp_match = target.corp_id in user_corp_ids

    parent = getattr(run, "parent_run", None)
    if not parent:
        parent = AuditRun.objects.select_related("target").filter(pk=getattr(run, "parent_run_id", None)).first()
    parent_corp_id = None
    parent_corp_name = None
    parent_corp_match = False
    if parent:
        parent_target = getattr(parent, "target", None)
        if parent_target and parent_target.target_type == AuditTarget.TARGET_CORP:
            parent_corp_id = parent_target.corp_id
            parent_corp_name = parent_target.corp_name
            if not is_admin:
                parent_corp_match = parent_target.corp_id in user_corp_ids

    visible = is_admin or started_by_match or automated_match or target_corp_match or parent_corp_match

    context = {
        "run": run,
        "is_admin": is_admin,
        "user_corp_ids": user_corp_ids,
        "started_by": started_by,
        "started_by_match": started_by_match,
        "automated_match": automated_match,
        "target_corp_id": target_corp_id,
        "target_corp_name": target_corp_name,
        "target_corp_match": target_corp_match,
        "parent_corp_id": parent_corp_id,
        "parent_corp_name": parent_corp_name,
        "parent_corp_match": parent_corp_match,
        "visible": visible,
    }
    return render(request, "securityaudit/debug_audit_visibility.html", context)
