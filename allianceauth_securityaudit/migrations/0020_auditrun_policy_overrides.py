from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0019_remove_auditpolicy_unused_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="policy_overrides",
            field=models.JSONField(blank=True, default=dict),
            preserve_default=False,
        ),
    ]
