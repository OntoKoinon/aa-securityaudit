from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="auditpolicy",
            options={
                "permissions": [
                    ("view_dashboard", "Can view security audit dashboard"),
                    ("view_summary", "Can view shareable security audit summaries"),
                    ("run_audit", "Can run manual security audits"),
                    ("manage_policy", "Can manage security audit policy"),
                    ("manage_enemies", "Can manage security audit enemy lists"),
                ]
            },
        )
    ]
