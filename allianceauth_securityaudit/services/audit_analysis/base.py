from dataclasses import dataclass, field

from ...models import AuditEvidence, AuditFinding

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
            ])
        return finding