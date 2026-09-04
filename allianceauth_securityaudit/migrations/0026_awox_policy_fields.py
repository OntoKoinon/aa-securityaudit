from decimal import Decimal

from django.db import migrations, models

import allianceauth_securityaudit.constants as constants


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0025_corp_overlap_thresholds"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_min_damage_share",
            field=models.DecimalField(
                decimal_places=2,
                default=constants.DEFAULT_AWOX_MIN_DAMAGE_SHARE,
                help_text="Minimum damage_done/damage_taken share for damage-ownership awox qualification (0.00-1.00).",
                max_digits=4,
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_lookback_days",
            field=models.PositiveIntegerField(
                default=constants.DEFAULT_AWOX_LOOKBACK_DAYS,
                help_text="How far back in kill history to consider awox kills.",
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_large_fleet_attacker_threshold",
            field=models.PositiveIntegerField(
                default=constants.DEFAULT_AWOX_LARGE_FLEET_ATTACKER_THRESHOLD,
                help_text="Attacker count at which the generalized crossfire exclusion applies (with hostiles present, low damage, not final blow, not tackle/HIC).",
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_solo_attacker_threshold",
            field=models.PositiveIntegerField(
                default=constants.DEFAULT_AWOX_SOLO_ATTACKER_THRESHOLD,
                help_text="Attacker count at or below which the solo/small-gang awox bonus is applied.",
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_min_victim_value",
            field=models.DecimalField(
                decimal_places=2,
                default=constants.DEFAULT_AWOX_MIN_VICTIM_VALUE,
                help_text="Minimum zkb total value for rookie ship/shuttle/corvette victims to avoid sparring exclusion. Pods are exempt.",
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="auditpolicy",
            name="awox_blue_scouting_bonus",
            field=models.PositiveIntegerField(
                default=constants.DEFAULT_AWOX_BLUE_SCOUTING_BONUS,
                help_text="Score bonus per kill qualified via the blue-scouting path (NPC-corp alt + main/other alts share corp/alliance with victim).",
            ),
        ),
    ]
