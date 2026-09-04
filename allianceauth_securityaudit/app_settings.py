from django.conf import settings


SECURITYAUDIT_ESI_BASE = getattr(settings, "SECURITYAUDIT_ESI_BASE", "https://esi.evetech.net/latest")
SECURITYAUDIT_ZKILL_BASE = getattr(settings, "SECURITYAUDIT_ZKILL_BASE", "https://zkillboard.com/api")
SECURITYAUDIT_USER_AGENT = getattr(
    settings,
    "SECURITYAUDIT_USER_AGENT",
    "AllianceAuth-SecurityAudit/0.1 (security audits)",
)
