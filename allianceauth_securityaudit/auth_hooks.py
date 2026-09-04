from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
from django.utils.translation import gettext_lazy as _


@hooks.register("url_hook")
def register_urls():
    return UrlHook("allianceauth_securityaudit.urls", "securityaudit", "securityaudit/")


class SecurityAuditMenuItemHook(MenuItemHook):
    def render(self, request):
        if not request.user.has_module_perms("securityaudit"):
            return ""
        return super().render(request)


@hooks.register("menu_item_hook")
def register_menu():
    return SecurityAuditMenuItemHook(
        _("Security Audit"),
        "fas fa-user-shield",
        "securityaudit:dashboard",
        navactive=[
            "securityaudit:dashboard",
            "securityaudit:run_audit",
            "securityaudit:policy_edit",
            "securityaudit:enemy_list",
            "securityaudit:financial_exception_list",
            "securityaudit:audit_jobs",
        ],
    )
