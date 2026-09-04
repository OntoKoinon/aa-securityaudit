from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0024_capital_asset_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="corp_overlap_rule1_min_corps",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 1 (both_close).",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="corp_overlap_rule2_min_corps",
            field=models.PositiveIntegerField(
                default=3,
                help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 2 (any_close).",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="corp_overlap_rule3_min_corps",
            field=models.PositiveIntegerField(
                default=5,
                help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 3 (no close match).",
            ),
            preserve_default=False,
        ),
    ]
