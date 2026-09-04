from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0005_alt_corp_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="esi_throttle_seconds",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.10"),
                help_text="Seconds to sleep between ESI calls during audits (0 disables throttling).",
                max_digits=4,
            ),
        ),
    ]
