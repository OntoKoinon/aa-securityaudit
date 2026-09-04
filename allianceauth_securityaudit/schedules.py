from django.conf import settings


def get_default_task_schedule_minutes():
    return getattr(settings, "SECURITYAUDIT_DEFAULT_AUTOMATION_FREQUENCY_MINUTES", 60)
