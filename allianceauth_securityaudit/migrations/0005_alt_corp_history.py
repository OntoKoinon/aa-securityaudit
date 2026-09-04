from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0004_alter_auditfinding_severity"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="alt_corp_history_min_shared_corps",
            field=models.PositiveIntegerField(default=2),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="alt_corp_history_max_join_leave_diff_hours",
            field=models.PositiveIntegerField(default=24),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="auditrelationshipcounterparty",
            name="counterparty_type",
            field=models.CharField(
                choices=[
                    ("isk_donation", "ISK Donation"),
                    ("plus_ten_standing", "+10 Standing"),
                    ("free_contract", "Free Contract"),
                    ("possible_alt", "Possible Alt"),
                    ("other", "Other"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="auditrelationshipcounterparty",
            name="notes",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
