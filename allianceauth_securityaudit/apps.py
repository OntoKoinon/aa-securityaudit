import logging

from django.apps import AppConfig
from django.conf import settings

LOGGER = logging.getLogger(__name__)


class SecurityAuditConfig(AppConfig):
    name = "allianceauth_securityaudit"
    label = "securityaudit"
    verbose_name = "Security Audit"

    def ready(self):
        installed = set(getattr(settings, "INSTALLED_APPS", []))
        if "memberaudit" not in installed:
            LOGGER.warning(
                "Security Audit requires MemberAudit to be installed and listed "
                "in INSTALLED_APPS. Without it, most audit checks (wallet data, "
                "corporation history, character snapshots, asset/ship tracking, "
                "contact standings) will be degraded or unavailable. "
                "Add 'memberaudit' to INSTALLED_APPS before "
                "'allianceauth_securityaudit'."
            )
