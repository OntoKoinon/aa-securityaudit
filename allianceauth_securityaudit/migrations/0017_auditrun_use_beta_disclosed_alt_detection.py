from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0016_auditpolicy_killmail_max_attacker_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="use_beta_disclosed_alt_detection",
            field=models.BooleanField(default=False),
        ),
    ]
