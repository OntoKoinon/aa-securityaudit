from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0012_remove_auditpolicy_included_corp_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="progress_details",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
