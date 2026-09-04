from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from ..models import AuditPolicy, AuditRun, AuditTarget
from .autogroups_adapter import AutogroupsAdapter
from .esi_client import EsiClient


def _extract_main_character_name(user):
    profile = getattr(user, "profile", None)
    if profile is None:
        return ""
    for attr in ("main_character_name", "main_character", "character_name"):
        value = getattr(profile, attr, None)
        if not value:
            continue
        if isinstance(value, str):
            return value.strip()
        nested_name = getattr(value, "character_name", None) or getattr(value, "name", None)
        if nested_name:
            return str(nested_name).strip()
    return ""


def discover_new_join_mains(policy: AuditPolicy):
    esi = EsiClient()
    window_start = timezone.now() - timedelta(days=policy.new_join_window_days)
    managed_ids = AutogroupsAdapter.get_managed_corp_ids()
    if not managed_ids:
        return []
    allowed_corps = managed_ids

    users = get_user_model().objects.all()
    rows = []
    for user in users:
        main_name = _extract_main_character_name(user)
        if not main_name:
            continue
        character_id = esi.resolve_character_name(main_name)
        if not character_id:
            continue
        try:
            character = esi.get_character(character_id)
            corp_history = esi.get_character_corp_history(character_id)
        except Exception:
            continue

        latest_join = None
        corp_id = None
        if corp_history:
            latest = max(corp_history, key=lambda x: x.get("record_id", 0))
            corp_id = latest.get("corporation_id")
            latest_join = esi.parse_esi_time(latest.get("start_date"))
        if not corp_id or corp_id not in allowed_corps:
            continue

        if latest_join and latest_join >= window_start:
            rows.append(
                {
                    "user_id": user.id,
                    "character_name": main_name,
                    "character_id": character_id,
                    "corp_id": corp_id,
                    "joined_at": latest_join,
                }
            )
    return rows


def queue_new_join_audits(policy: AuditPolicy):
    queued = []
    for row in discover_new_join_mains(policy):
        target, _ = AuditTarget.objects.get_or_create(
            target_type=AuditTarget.TARGET_INDIVIDUAL,
            character_name=row["character_name"],
            defaults={
                "character_id": row["character_id"],
                "corp_id": row["corp_id"],
            },
        )
        existing_automated = AuditRun.objects.filter(target=target, automated=True).exists()
        if existing_automated:
            continue
        run = AuditRun.objects.create(target=target, automated=True, status=AuditRun.STATUS_QUEUED)
        queued.append(run)
    return queued
