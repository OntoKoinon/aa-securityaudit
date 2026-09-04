from decimal import Decimal

from django.db import migrations, models

import allianceauth_securityaudit.constants


class Migration(migrations.Migration):

    dependencies = [
        ("securityaudit", "0022_auditcapitalshipobservation"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="zkill_throttle_seconds",
            field=models.DecimalField(
                decimal_places=2,
                default=allianceauth_securityaudit.constants.DEFAULT_ZKILL_THROTTLE_SECONDS,
                help_text="Seconds to sleep between zKill API calls during audits (0 disables throttling).",
                max_digits=4,
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="zkill_kill_pages",
            field=models.PositiveIntegerField(
                default=allianceauth_securityaudit.constants.DEFAULT_ZKILL_KILL_PAGES,
                help_text="Number of zKill pages to fetch for general kill history per character.",
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="zkill_loss_pages",
            field=models.PositiveIntegerField(
                default=allianceauth_securityaudit.constants.DEFAULT_ZKILL_LOSS_PAGES,
                help_text="Number of zKill pages to fetch for general loss history per character.",
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="zkill_capital_kill_pages",
            field=models.PositiveIntegerField(
                default=allianceauth_securityaudit.constants.DEFAULT_ZKILL_CAPITAL_KILL_PAGES,
                help_text=(
                    "Number of zKill pages to fetch per capital ship group when scanning "
                    "attacker-side capital kills per character."
                ),
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="zkill_capital_loss_pages",
            field=models.PositiveIntegerField(
                default=allianceauth_securityaudit.constants.DEFAULT_ZKILL_CAPITAL_LOSS_PAGES,
                help_text=(
                    "Number of zKill pages to fetch per capital ship group when scanning "
                    "capital losses per character."
                ),
            ),
        ),
    ]
