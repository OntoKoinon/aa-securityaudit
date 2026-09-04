from django.contrib import admin

from .models import (
    AuditEvidence,
    AuditFinding,
    AuditPolicy,
    AuditRelationshipCounterparty,
    AuditRun,
    AuditTarget,
    EnemyEntity,
)


@admin.register(AuditPolicy)
class AuditPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "automation_enabled", "updated_at")


@admin.register(EnemyEntity)
class EnemyEntityAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "entity_id", "label", "is_active", "created_at")
    list_filter = ("entity_type", "is_active")
    search_fields = ("label", "entity_id")


@admin.register(AuditTarget)
class AuditTargetAdmin(admin.ModelAdmin):
    list_display = ("target_type", "character_name", "character_id", "corp_id", "corp_name")
    list_filter = ("target_type",)
    search_fields = ("character_name", "corp_name", "character_id", "corp_id")


class AuditEvidenceInline(admin.TabularInline):
    model = AuditEvidence
    extra = 0


@admin.register(AuditFinding)
class AuditFindingAdmin(admin.ModelAdmin):
    list_display = ("audit_run", "finding_type", "severity", "score_impact", "created_at")
    list_filter = ("finding_type", "severity")
    inlines = [AuditEvidenceInline]


@admin.register(AuditRelationshipCounterparty)
class AuditRelationshipCounterpartyAdmin(admin.ModelAdmin):
    list_display = (
        "audit_run",
        "counterparty_type",
        "character_name",
        "character_id",
        "total_amount",
        "event_count",
    )
    list_filter = ("counterparty_type",)


@admin.register(AuditRun)
class AuditRunAdmin(admin.ModelAdmin):
    list_display = ("id", "target", "status", "risk_level", "risk_score", "automated", "created_at")
    list_filter = ("status", "risk_level", "automated")
    search_fields = ("id", "target__character_name", "target__corp_name")
