from django.db import migrations, models

import allianceauth_securityaudit.constants as constants


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0010_cleanup_securityaudit_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="summary_link_expiry_hours",
            field=models.PositiveIntegerField(
                default=constants.DEFAULT_SUMMARY_LINK_EXPIRY_HOURS,
                help_text="Hours until a generated shareable summary link expires.",
            ),
        ),
    ]
