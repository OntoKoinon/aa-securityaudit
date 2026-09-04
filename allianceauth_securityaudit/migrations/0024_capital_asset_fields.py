from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0023_auditpolicy_zkill_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditcapitalshipobservation",
            name="asset_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="auditcapitalshipobservation",
            name="is_current_ship",
            field=models.BooleanField(default=False),
        ),
    ]
