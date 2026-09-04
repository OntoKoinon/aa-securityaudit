from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    db_alias = schema_editor.connection.alias

    try:
        ct = ContentType.objects.using(db_alias).get(app_label="securityaudit", model="auditpolicy")
    except ContentType.DoesNotExist:
        return

    # Rename the old view_summary permission to view_summaries.
    Permission.objects.using(db_alias).filter(
        codename="view_summary", content_type=ct
    ).update(codename="view_summaries", name="Can view security audit summaries")

    # Grant administrate to everyone who currently has manage_policy.
    try:
        manage_perm = Permission.objects.using(db_alias).get(
            codename="manage_policy",
            content_type=ct,
        )
    except Permission.DoesNotExist:
        manage_perm = None

    if manage_perm:
        admin_perm, _ = Permission.objects.using(db_alias).get_or_create(
            codename="administrate",
            content_type=ct,
            defaults={"name": "Can administrate security audits"},
        )
        for user in manage_perm.user_set.all():
            user.user_permissions.add(admin_perm)
        for group in manage_perm.group_set.all():
            group.permissions.add(admin_perm)
        manage_perm.delete()

    # Ensure the new permissions exist for installations that don't have them yet.
    for codename, name in (
        ("view_summaries", "Can view security audit summaries"),
        ("administrate", "Can administrate security audits"),
        ("generate_link", "Can generate shareable security audit summary links"),
    ):
        Permission.objects.using(db_alias).get_or_create(
            codename=codename,
            content_type=ct,
            defaults={"name": name},
        )


def cleanup_stale_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    db_alias = schema_editor.connection.alias

    allowed = {
        "view_dashboard",
        "view_summaries",
        "run_audit",
        "administrate",
        "generate_link",
        "manage_enemies",
    }
    Permission.objects.using(db_alias).filter(
        content_type__app_label="securityaudit"
    ).exclude(codename__in=allowed).delete()


def reverse_migrate(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0008_auditrun_parent_run"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="auditpolicy",
            options={
                "default_permissions": [],
                "permissions": [
                    ("view_dashboard", "Can view security audit dashboard"),
                    ("view_summaries", "Can view security audit summaries"),
                    ("run_audit", "Can run manual security audits"),
                    ("administrate", "Can administrate security audits"),
                    ("generate_link", "Can generate shareable security audit summary links"),
                    ("manage_enemies", "Can manage security audit enemy lists"),
                ]
            },
        ),
        migrations.AlterModelOptions(name="enemyentity", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="audittarget", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditrun", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditfinding", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditevidence", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditrelationshipcounterparty", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditsummaryview", options={"default_permissions": []}),
        migrations.CreateModel(
            name="AuditSummaryLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=64, unique=True, db_index=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="summary_links",
                        to="securityaudit.auditrun",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="securityaudit_summary_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "default_permissions": [],
            },
        ),
        migrations.RunPython(migrate_permissions, reverse_migrate),
        migrations.RunPython(cleanup_stale_permissions, reverse_migrate),
    ]
