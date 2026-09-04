from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0026_awox_policy_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditcapitalshipobservation",
            name="contract_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of active contracts involving this capital ship type.",
            ),
        ),
        migrations.AddField(
            model_name="auditcapitalshipobservation",
            name="market_order_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of active sell orders for this capital ship type.",
            ),
        ),
    ]
