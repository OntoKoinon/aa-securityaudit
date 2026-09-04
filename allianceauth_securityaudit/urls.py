from django.urls import path

from . import views

app_name = "securityaudit"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/live-status/", views.dashboard_live_status, name="dashboard_live_status"),
    path("run/", views.run_audit, name="run_audit"),
    path("autocomplete/corporations/", views.autocomplete_corporations, name="autocomplete_corporations"),
    path("autocomplete/characters/", views.autocomplete_characters, name="autocomplete_characters"),
    path("audit/<int:audit_id>/progress/", views.audit_progress, name="audit_progress"),
    path("audit/<int:audit_id>/", views.audit_detail, name="audit_detail"),
    path("audit/<int:audit_id>/rerun/", views.audit_rerun, name="audit_rerun"),
    path("audit/<int:audit_id>/requeue/", views.audit_requeue, name="audit_requeue"),
    path("audit/<int:audit_id>/stop/", views.audit_stop, name="audit_stop"),
    path("audit/<int:audit_id>/delete/", views.audit_delete, name="audit_delete"),
    path("audits/bulk-delete/", views.audit_bulk_delete, name="audit_bulk_delete"),
    path("audits/bulk-requeue/", views.audit_bulk_requeue, name="audit_bulk_requeue"),
    path("audit/<int:audit_id>/summary/", views.audit_summary, name="audit_summary"),
    path("audit/<int:audit_id>/generate-link/", views.generate_summary_link, name="generate_summary_link"),
    path("policy/", views.policy_edit, name="policy_edit"),
    path("enemies/", views.enemy_list, name="enemy_list"),
    path("enemies/autocomplete/", views.enemy_autocomplete, name="enemy_autocomplete"),
    path("enemies/add/", views.enemy_add, name="enemy_add"),
    path("enemies/<int:enemy_id>/delete/", views.enemy_delete, name="enemy_delete"),
    path("exceptions/", views.financial_exception_list, name="financial_exception_list"),
    path("exceptions/autocomplete/", views.financial_exception_autocomplete, name="financial_exception_autocomplete"),
    path("exceptions/add/", views.financial_exception_add, name="financial_exception_add"),
    path("exceptions/<int:exception_id>/edit/", views.financial_exception_edit, name="financial_exception_edit"),
    path("exceptions/<int:exception_id>/delete/", views.financial_exception_delete, name="financial_exception_delete"),
    path("jobs/process-new-joins/", views.run_new_join_job, name="run_new_join_job"),
    path("jobs/", views.audit_jobs, name="audit_jobs"),
    path("jobs/recover-stale/", views.audit_recover_stale, name="audit_recover_stale"),
    path("debug/permissions/", views.debug_permissions, name="debug_permissions"),
    path("debug/audit/<int:audit_id>/", views.debug_audit_visibility, name="debug_audit_visibility"),
]
