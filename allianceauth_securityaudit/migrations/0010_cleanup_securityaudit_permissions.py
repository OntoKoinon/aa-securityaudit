from django.db import migrations


def cleanup_and_ensure(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    db_alias = schema_editor.connection.alias

    try:
        ct = ContentType.objects.using(db_alias).get(
            app_label="securityaudit", model="auditpolicy"
        )
    except ContentType.DoesNotExist:
        return

    allowed = {
        "view_dashboard",
        "view_summaries",
        "run_audit",
        "administrate",
        "generate_link",
        "manage_enemies",
    }

    # Rename the old view_summary permission to view_summaries if it is still present.
    Permission.objects.using(db_alias).filter(
        codename="view_summary", content_type=ct
    ).update(codename="view_summaries", name="Can view security audit summaries")

    # Grant administrate to anyone who still has manage_policy.
    try:
        manage_perm = Permission.objects.using(db_alias).get(
            codename="manage_policy", content_type=ct
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

    # Ensure the new permissions exist.
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

    # Remove any securityaudit permission that is not part of the new set.
    Permission.objects.using(db_alias).filter(
        content_type__app_label="securityaudit"
    ).exclude(codename__in=allowed).delete()


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0009_permissions_and_summarylink"),
    ]

    operations = [
        migrations.AlterModelOptions(name="auditpolicy", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="enemyentity", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="audittarget", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditrun", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditfinding", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditevidence", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditrelationshipcounterparty", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditsummaryview", options={"default_permissions": []}),
        migrations.AlterModelOptions(name="auditsummarylink", options={"default_permissions": []}),
        migrations.RunPython(cleanup_and_ensure, reverse),
    ]
