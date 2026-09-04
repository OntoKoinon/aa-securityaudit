from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0020_auditrun_policy_overrides"),
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
                    ("view_enemies", "Can view security audit enemy lists"),
                ],
            },
        ),
    ]
