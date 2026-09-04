from django.db import migrations


def fix_child_automated(apps, schema_editor):
    AuditRun = apps.get_model("securityaudit", "AuditRun")
    for child in AuditRun.objects.filter(parent_run__isnull=False):
        parent = child.parent_run
        if parent and child.automated != parent.automated:
            child.automated = parent.automated
            child.save(update_fields=["automated"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0014_auditrun_task_id"),
    ]

    operations = [
        migrations.RunPython(fix_child_automated, noop),
    ]
