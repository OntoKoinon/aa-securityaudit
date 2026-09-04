from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0015_fix_child_automated"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="killmail_max_attacker_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Maximum number of attackers on a killmail to include it in analysis. 0 means no limit.",
            ),
            preserve_default=False,
        ),
    ]
