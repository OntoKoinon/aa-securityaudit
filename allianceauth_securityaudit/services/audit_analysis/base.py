from dataclasses import dataclass, field

from ...models import AuditEvidence, AuditFinding, EnemyEntity


@dataclass
class AuditResult:
    risk_score: int
    risk_level: str
    summary: str
    missing_scopes: list[str]
    child_run_ids: list[int] = field(default_factory=list)


class BaseAuditMixin:

    @staticmethod
    def _risk_level(score):
        if score >= 100:
            return "critical"
        if score >= 70:
            return "high"
        if score >= 35:
            return "medium"
        return "low"

    def _get_enemy_sets(self):
        """Load all active enemy entity IDs once per audit run and cache on self.

        Returns a tuple of (enemy_character_ids, enemy_corp_ids, enemy_alliance_ids)
        as sets. Subsequent calls return the cached values, avoiding repeated
        queries across awox, collusion, enemy, and plus_ten analysis modules.
        """
        cached = getattr(self, "_enemy_sets_cache", None)
        if cached is not None:
            return cached
        enemy_character_ids = set()
        enemy_corp_ids = set()
        enemy_alliance_ids = set()
        for etype, eid in EnemyEntity.objects.filter(is_active=True).values_list(
            "entity_type", "entity_id"
        ):
            if etype == EnemyEntity.TYPE_CHARACTER:
                enemy_character_ids.add(eid)
            elif etype == EnemyEntity.TYPE_CORP:
                enemy_corp_ids.add(eid)
            elif etype == EnemyEntity.TYPE_ALLIANCE:
                enemy_alliance_ids.add(eid)
        cached = (enemy_character_ids, enemy_corp_ids, enemy_alliance_ids)
        self._enemy_sets_cache = cached
        return cached

    @staticmethod
    def _create_finding(audit_run, finding_type, severity, title, details, score_impact, evidence=None):
        finding = AuditFinding.objects.create(
            audit_run=audit_run,
            finding_type=finding_type,
            severity=severity,
            title=title,
            details=details,
            score_impact=score_impact,
        )
        if evidence:
            AuditEvidence.objects.bulk_create([
                AuditEvidence(finding=finding, key=key, value=str(value))
                for key, value in evidence
            ], batch_size=500)
        return finding