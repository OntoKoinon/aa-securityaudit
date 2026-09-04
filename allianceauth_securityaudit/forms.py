from decimal import Decimal

from django import forms

from .models import AuditPolicy, AuditTarget, EnemyEntity, FinancialException


class RangeInput(forms.NumberInput):
    input_type = "range"


class AuditRunForm(forms.Form):
    OVERRIDE_FIELDS = [
        "large_donation_isk_threshold",
        "free_contract_value_threshold",
        "corp_hop_window_days",
        "corp_hop_count_threshold",
        "alt_corp_history_max_join_leave_diff_hours",
        "corp_overlap_rule1_min_corps",
        "corp_overlap_rule2_min_corps",
        "corp_overlap_rule3_min_corps",
        "killmail_max_attacker_count",
        "awox_min_damage_share",
        "awox_lookback_days",
        "awox_large_fleet_attacker_threshold",
        "awox_solo_attacker_threshold",
        "awox_min_victim_value",
        "awox_blue_scouting_bonus",
    ]

    target_type = forms.ChoiceField(
        choices=AuditTarget.TARGET_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # Audit option toggles — all checked by default except standard (which is
    # always on and cannot be unchecked). These are stored in policy_overrides
    # under the "__audit_options__" key and read by the engine to skip checks.
    check_undisclosed_alts = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    check_capital_observations = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    check_awox = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    character_name = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Character name",
                "autocomplete": "off",
            }
        ),
    )
    character_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    corporation_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    corporation_name = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Corporation name",
                "autocomplete": "off",
            }
        ),
    )

    large_donation_isk_threshold = forms.DecimalField(
        required=False,
        min_value=Decimal("500000000"),
        max_value=Decimal("10000000000"),
        max_digits=20,
        decimal_places=2,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "500000000",
                "max": "10000000000",
                "step": "100000000",
            }
        ),
    )
    free_contract_value_threshold = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("10000000000"),
        max_digits=20,
        decimal_places=2,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "0",
                "max": "10000000000",
                "step": "100000000",
            }
        ),
    )
    corp_hop_window_days = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "365",
                "step": "1",
            }
        ),
    )
    corp_hop_count_threshold = forms.IntegerField(
        required=False,
        min_value=2,
        max_value=10,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "2",
                "max": "10",
                "step": "1",
            }
        ),
    )
    alt_corp_history_max_join_leave_diff_hours = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=168,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "168",
                "step": "1",
            }
        ),
    )
    corp_overlap_rule1_min_corps = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "10",
                "step": "1",
            }
        ),
    )
    corp_overlap_rule2_min_corps = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "10",
                "step": "1",
            }
        ),
    )
    corp_overlap_rule3_min_corps = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "10",
                "step": "1",
            }
        ),
    )
    killmail_max_attacker_count = forms.IntegerField(
        required=False,
        min_value=2,
        max_value=200,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "2",
                "max": "200",
                "step": "1",
            }
        ),
    )
    awox_min_damage_share = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        max_digits=4,
        decimal_places=2,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "0",
                "max": "1",
                "step": "0.05",
            }
        ),
    )
    awox_lookback_days = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=730,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "730",
                "step": "1",
            }
        ),
    )
    awox_large_fleet_attacker_threshold = forms.IntegerField(
        required=False,
        min_value=2,
        max_value=200,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "2",
                "max": "200",
                "step": "1",
            }
        ),
    )
    awox_solo_attacker_threshold = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "1",
                "max": "50",
                "step": "1",
            }
        ),
    )
    awox_min_victim_value = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("10000000000"),
        max_digits=20,
        decimal_places=2,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "0",
                "max": "10000000000",
                "step": "1000000",
            }
        ),
    )
    awox_blue_scouting_bonus = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        widget=RangeInput(
            attrs={
                "class": "form-range",
                "min": "0",
                "max": "100",
                "step": "1",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        policy = AuditPolicy.get_solo()
        labels = {
            "large_donation_isk_threshold": "Large Donation Threshold (ISK)",
            "free_contract_value_threshold": "Free Contract Value Threshold (ISK)",
            "corp_hop_window_days": "Corp Hop Window (days)",
            "corp_hop_count_threshold": "Corp Hop Count Threshold",
            "alt_corp_history_max_join_leave_diff_hours": "Alt Corp History Max. Join/Leave Diff (hours)",
            "corp_overlap_rule1_min_corps": "Corp Overlap Rule 1 Min. Corps",
            "corp_overlap_rule2_min_corps": "Corp Overlap Rule 2 Min. Corps",
            "corp_overlap_rule3_min_corps": "Corp Overlap Rule 3 Min. Corps",
            "killmail_max_attacker_count": "Killmail Max. Attacker Count",
            "awox_min_damage_share": "Awox Min. Damage Share",
            "awox_lookback_days": "Awox Lookback (days)",
            "awox_large_fleet_attacker_threshold": "Awox Large Fleet Attacker Threshold",
            "awox_solo_attacker_threshold": "Awox Solo Attacker Threshold",
            "awox_min_victim_value": "Awox Min. Victim Value (ISK)",
            "awox_blue_scouting_bonus": "Awox Blue Scouting Bonus",
        }
        help_texts = {
            "corp_overlap_rule1_min_corps": (
                "<strong>Rule 1 &mdash; Strong alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps have <em>both</em> join and leave dates "
                "within the max join/leave diff window (both_close).<br><br>"
                "<strong>Scoring:</strong> base 60 + 5 per additional qualifying corp "
                "+ 10 per additional both_close corp (or +5 if only any_close).<br>"
                "The highest-scoring rule wins."
            ),
            "corp_overlap_rule2_min_corps": (
                "<strong>Rule 2 &mdash; Moderate alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps have <em>either</em> join or leave dates "
                "within the max join/leave diff window (any_close).<br><br>"
                "<strong>Scoring:</strong> base 40 + 5 per additional qualifying corp beyond the threshold "
                "+ 5 per additional any_close corp.<br>"
                "The highest-scoring rule wins."
            ),
            "corp_overlap_rule3_min_corps": (
                "<strong>Rule 3 &mdash; Weak alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps are shared but none have close "
                "join/leave dates.<br><br>"
                "<strong>Scoring:</strong> base 10 + 5 per additional qualifying corp beyond the threshold.<br>"
                "The highest-scoring rule wins."
            ),
        }
        for name in self.OVERRIDE_FIELDS:
            self.fields[name].label = labels.get(name, self.fields[name].label)
            self.fields[name].help_text = help_texts.get(name, "")
            self.fields[name].initial = getattr(policy, name)

    def clean(self):
        cleaned = super().clean()
        target_type = cleaned.get("target_type")
        character_name = (cleaned.get("character_name") or "").strip()
        corporation_name = (cleaned.get("corporation_name") or "").strip()
        if target_type == AuditTarget.TARGET_INDIVIDUAL and not character_name:
            self.add_error("character_name", "Character name is required for individual audits.")
        if target_type == AuditTarget.TARGET_CORP and not corporation_name:
            self.add_error("corporation_name", "Corporation name is required for corporation audits.")
        cleaned["character_name"] = character_name
        cleaned["corporation_name"] = corporation_name

        policy = AuditPolicy.get_solo()
        overrides = {}
        for name in self.OVERRIDE_FIELDS:
            value = cleaned.get(name)
            if value is not None and value != getattr(policy, name):
                overrides[name] = str(value) if isinstance(value, Decimal) else value

        # Audit option toggles — stored under a reserved key in policy_overrides.
        overrides["__audit_options__"] = {
            "check_undisclosed_alts": bool(cleaned.get("check_undisclosed_alts", True)),
            "check_capital_observations": bool(cleaned.get("check_capital_observations", True)),
            "check_awox": bool(cleaned.get("check_awox", True)),
        }
        cleaned["policy_overrides"] = overrides

        return cleaned


class AuditPolicyForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        labels = {
            "enabled": "Audits Enabled",
            "automation_enabled": "Automated Audits Enabled",
            "new_join_window_days": "New Join Lookback Window (days)",
            "large_donation_isk_threshold": "Large Donation Threshold (ISK)",
            "free_contract_value_threshold": "Free Contract Value Threshold (ISK)",
            "corp_hop_window_days": "Corp Hop Window (days)",
            "corp_hop_count_threshold": "Corp Hop Count Threshold",
            "alt_corp_history_max_join_leave_diff_hours": "Alt Corp History Max. Join/Leave Diff (hours)",
            "corp_overlap_rule1_min_corps": "Corp Overlap Rule 1 Min. Corps",
            "corp_overlap_rule2_min_corps": "Corp Overlap Rule 2 Min. Corps",
            "corp_overlap_rule3_min_corps": "Corp Overlap Rule 3 Min. Corps",
            "esi_throttle_seconds": "ESI Throttle (seconds)",
            "summary_link_expiry_hours": "Summary Link Expiry (hours)",
            "killmail_max_attacker_count": "Killmail Max. Attacker Count",
            "zkill_throttle_seconds": "zKill Throttle (seconds)",
            "zkill_kill_pages": "zKill Kill Pages",
            "zkill_loss_pages": "zKill Loss Pages",
            "zkill_capital_kill_pages": "zKill Capital Kill Pages",
            "zkill_capital_loss_pages": "zKill Capital Loss Pages",
            "awox_min_damage_share": "Awox Min. Damage Share",
            "awox_lookback_days": "Awox Lookback (days)",
            "awox_large_fleet_attacker_threshold": "Awox Large Fleet Attacker Threshold",
            "awox_solo_attacker_threshold": "Awox Solo Attacker Threshold",
            "awox_min_victim_value": "Awox Min. Victim Value (ISK)",
            "awox_blue_scouting_bonus": "Awox Blue Scouting Bonus",
        }

        help_texts = {
            "new_join_window_days": "How far back to look when finding recently-joined characters to audit automatically.",
            "large_donation_isk_threshold": "A single incoming ISK transfer above this value is flagged as a large donation.",
            "free_contract_value_threshold": "Contracts received with a value above this threshold and no charge are flagged.",
            "corp_hop_window_days": "Time window in which repeated corporation changes are counted as \"hopping\".",
            "corp_hop_count_threshold": "Number of corporation changes within the window that triggers a flight-risk finding.",
            "alt_corp_history_max_join_leave_diff_hours": "Maximum time difference between join/leave dates when comparing corporation histories across possible alts.",
            "corp_overlap_rule1_min_corps": (
                "<strong>Rule 1 &mdash; Strong alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps have <em>both</em> join and leave dates "
                "within the max join/leave diff window (both_close).<br><br>"
                "<strong>Scoring:</strong> base 60 + 5 per additional qualifying corp "
                "+ 10 per additional both_close corp (or +5 if only any_close).<br>"
                "The highest-scoring rule wins."
            ),
            "corp_overlap_rule2_min_corps": (
                "<strong>Rule 2 &mdash; Moderate alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps have <em>either</em> join or leave dates "
                "within the max join/leave diff window (any_close).<br><br>"
                "<strong>Scoring:</strong> base 40 + 5 per additional qualifying corp beyond the threshold "
                "+ 5 per additional any_close corp.<br>"
                "The highest-scoring rule wins."
            ),
            "corp_overlap_rule3_min_corps": (
                "<strong>Rule 3 &mdash; Weak alt signal</strong><br>"
                "Fires when &ge; this many qualifying non-NPC corps are shared but none have close "
                "join/leave dates.<br><br>"
                "<strong>Scoring:</strong> base 10 + 5 per additional qualifying corp beyond the threshold.<br>"
                "The highest-scoring rule wins."
            ),
            "esi_throttle_seconds": "Seconds to sleep between ESI calls during audits (0 disables throttling).",
            "summary_link_expiry_hours": "Hours until a generated shareable summary link expires.",
            "killmail_max_attacker_count": "Maximum number of attackers on a killmail to include it in analysis. 0 means no limit.",
            "zkill_throttle_seconds": "Seconds to sleep between zKill API calls during audits (0 disables throttling).",
            "zkill_kill_pages": "Number of zKill pages to fetch for general kill history per character.",
            "zkill_loss_pages": "Number of zKill pages to fetch for general loss history per character.",
            "zkill_capital_kill_pages": "Pages to fetch per capital ship group when scanning attacker-side capital kills per character.",
            "zkill_capital_loss_pages": "Pages to fetch per capital ship group when scanning capital losses per character.",
            "awox_min_damage_share": "Minimum damage_done/damage_taken share for damage-ownership awox qualification (0.00-1.00). Below this (and not final blow, not tackle, not HIC) the kill is excluded as whoring.",
            "awox_lookback_days": "How far back in kill history to consider awox kills. Kills older than this are ignored.",
            "awox_large_fleet_attacker_threshold": "Attacker count at which the generalized crossfire exclusion applies (with hostiles present, low damage, not final blow, not tackle/HIC).",
            "awox_solo_attacker_threshold": "Attacker count at or below which the solo/small-gang awox bonus is applied.",
            "awox_min_victim_value": "Minimum zkb total value for rookie ship/shuttle/corvette victims to avoid sparring exclusion. Pods are exempt.",
            "awox_blue_scouting_bonus": "Score bonus per kill qualified via the blue-scouting path (NPC-corp alt + main/other alts share corp/alliance with victim).",
        }

        self.fieldsets = [
            ("Master switches", ["enabled"]),
            ("Automation", ["automation_enabled", "new_join_window_days"]),
            ("ISK / wallet", ["large_donation_isk_threshold"]),
            ("Contracts", ["free_contract_value_threshold"]),
            ("Corporation movement (flight risk)", ["corp_hop_window_days", "corp_hop_count_threshold"]),
            ("Undisclosed alts (corp history)", ["alt_corp_history_max_join_leave_diff_hours", "corp_overlap_rule1_min_corps", "corp_overlap_rule2_min_corps", "corp_overlap_rule3_min_corps"]),
            ("Killmails", ["killmail_max_attacker_count"]),
            ("Awox / friendly fire", ["awox_min_damage_share", "awox_lookback_days", "awox_large_fleet_attacker_threshold", "awox_solo_attacker_threshold", "awox_min_victim_value", "awox_blue_scouting_bonus"]),
            ("zKill", ["zkill_throttle_seconds", "zkill_kill_pages", "zkill_loss_pages", "zkill_capital_kill_pages", "zkill_capital_loss_pages"]),
            ("Infrastructure", ["esi_throttle_seconds", "summary_link_expiry_hours"]),
        ]

        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            field.help_text = help_texts.get(name, "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    class Meta:
        model = AuditPolicy
        fields = [
            "enabled",
            "automation_enabled",
            "new_join_window_days",
            "large_donation_isk_threshold",
            "free_contract_value_threshold",
            "corp_hop_window_days",
            "corp_hop_count_threshold",
            "alt_corp_history_max_join_leave_diff_hours",
            "corp_overlap_rule1_min_corps",
            "corp_overlap_rule2_min_corps",
            "corp_overlap_rule3_min_corps",
            "esi_throttle_seconds",
            "summary_link_expiry_hours",
            "killmail_max_attacker_count",
            "zkill_throttle_seconds",
            "zkill_kill_pages",
            "zkill_loss_pages",
            "zkill_capital_kill_pages",
            "zkill_capital_loss_pages",
            "awox_min_damage_share",
            "awox_lookback_days",
            "awox_large_fleet_attacker_threshold",
            "awox_solo_attacker_threshold",
            "awox_min_victim_value",
            "awox_blue_scouting_bonus",
        ]


class EnemyEntityForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    class Meta:
        model = EnemyEntity
        fields = ["entity_type", "entity_id", "label", "is_active", "notes"]


class FinancialExceptionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control w-100")
        self.fields["notes"].widget.attrs.pop("cols", None)
        self.fields["notes"].widget.attrs.setdefault("rows", "4")

    class Meta:
        model = FinancialException
        fields = ["entity_type", "entity_id", "label", "is_active", "notes"]
