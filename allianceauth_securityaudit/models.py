import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import (
    DEFAULT_ALT_CORP_HISTORY_MAX_JOIN_LEAVE_DIFF_HOURS,
    DEFAULT_AWOX_BLUE_SCOUTING_BONUS,
    DEFAULT_AWOX_LARGE_FLEET_ATTACKER_THRESHOLD,
    DEFAULT_AWOX_LOOKBACK_DAYS,
    DEFAULT_AWOX_MIN_DAMAGE_SHARE,
    DEFAULT_AWOX_MIN_VICTIM_VALUE,
    DEFAULT_AWOX_SOLO_ATTACKER_THRESHOLD,
    DEFAULT_CORP_OVERLAP_RULE1_MIN_CORPS,
    DEFAULT_CORP_OVERLAP_RULE2_MIN_CORPS,
    DEFAULT_CORP_OVERLAP_RULE3_MIN_CORPS,
    DEFAULT_FREE_CONTRACT_THRESHOLD,
    DEFAULT_KILLMAIL_MAX_ATTACKER_COUNT,
    DEFAULT_LARGE_DONATION_THRESHOLD,
    DEFAULT_NEW_JOIN_WINDOW_DAYS,
    DEFAULT_SUMMARY_LINK_EXPIRY_HOURS,
    DEFAULT_ZKILL_CAPITAL_KILL_PAGES,
    DEFAULT_ZKILL_CAPITAL_LOSS_PAGES,
    DEFAULT_ZKILL_KILL_PAGES,
    DEFAULT_ZKILL_LOSS_PAGES,
    DEFAULT_ZKILL_THROTTLE_SECONDS,
)


def _generate_summary_token():
    return secrets.token_hex(32)


class AuditPolicy(models.Model):
    name = models.CharField(max_length=64, unique=True, default="default")
    enabled = models.BooleanField(default=True)
    automation_enabled = models.BooleanField(default=True)
    new_join_window_days = models.PositiveIntegerField(default=DEFAULT_NEW_JOIN_WINDOW_DAYS)

    large_donation_isk_threshold = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=DEFAULT_LARGE_DONATION_THRESHOLD,
    )
    free_contract_value_threshold = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=DEFAULT_FREE_CONTRACT_THRESHOLD,
    )

    corp_hop_window_days = models.PositiveIntegerField(default=90)
    corp_hop_count_threshold = models.PositiveIntegerField(default=3)
    alt_corp_history_max_join_leave_diff_hours = models.PositiveIntegerField(default=DEFAULT_ALT_CORP_HISTORY_MAX_JOIN_LEAVE_DIFF_HOURS)
    corp_overlap_rule1_min_corps = models.PositiveIntegerField(
        default=DEFAULT_CORP_OVERLAP_RULE1_MIN_CORPS,
        help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 1 (both_close).",
    )
    corp_overlap_rule2_min_corps = models.PositiveIntegerField(
        default=DEFAULT_CORP_OVERLAP_RULE2_MIN_CORPS,
        help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 2 (any_close).",
    )
    corp_overlap_rule3_min_corps = models.PositiveIntegerField(
        default=DEFAULT_CORP_OVERLAP_RULE3_MIN_CORPS,
        help_text="Minimum qualifying non-NPC corps to trigger beta overlap rule 3 (no close match).",
    )
    esi_throttle_seconds = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.10"),
        help_text="Seconds to sleep between ESI calls during audits (0 disables throttling).",
    )
    summary_link_expiry_hours = models.PositiveIntegerField(
        default=DEFAULT_SUMMARY_LINK_EXPIRY_HOURS,
        help_text="Hours until a generated shareable summary link expires.",
    )
    killmail_max_attacker_count = models.PositiveIntegerField(
        default=DEFAULT_KILLMAIL_MAX_ATTACKER_COUNT,
        help_text="Maximum number of attackers on a killmail to include it in analysis. 0 means no limit.",
    )
    zkill_throttle_seconds = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=DEFAULT_ZKILL_THROTTLE_SECONDS,
        help_text="Seconds to sleep between zKill API calls during audits (0 disables throttling).",
    )
    zkill_kill_pages = models.PositiveIntegerField(
        default=DEFAULT_ZKILL_KILL_PAGES,
        help_text="Number of zKill pages to fetch for general kill history per character.",
    )
    zkill_loss_pages = models.PositiveIntegerField(
        default=DEFAULT_ZKILL_LOSS_PAGES,
        help_text="Number of zKill pages to fetch for general loss history per character.",
    )
    zkill_capital_kill_pages = models.PositiveIntegerField(
        default=DEFAULT_ZKILL_CAPITAL_KILL_PAGES,
        help_text="Number of zKill pages to fetch per capital ship group when scanning attacker-side capital kills per character.",
    )
    zkill_capital_loss_pages = models.PositiveIntegerField(
        default=DEFAULT_ZKILL_CAPITAL_LOSS_PAGES,
        help_text="Number of zKill pages to fetch per capital ship group when scanning capital losses per character.",
    )
    awox_min_damage_share = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=DEFAULT_AWOX_MIN_DAMAGE_SHARE,
        help_text="Minimum damage_done/damage_taken share for damage-ownership awox qualification (0.00-1.00).",
    )
    awox_lookback_days = models.PositiveIntegerField(
        default=DEFAULT_AWOX_LOOKBACK_DAYS,
        help_text="How far back in kill history to consider awox kills.",
    )
    awox_large_fleet_attacker_threshold = models.PositiveIntegerField(
        default=DEFAULT_AWOX_LARGE_FLEET_ATTACKER_THRESHOLD,
        help_text="Attacker count at which the generalized crossfire exclusion applies (with hostiles present, low damage, not final blow, not tackle/HIC).",
    )
    awox_solo_attacker_threshold = models.PositiveIntegerField(
        default=DEFAULT_AWOX_SOLO_ATTACKER_THRESHOLD,
        help_text="Attacker count at or below which the solo/small-gang awox bonus is applied.",
    )
    awox_min_victim_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=DEFAULT_AWOX_MIN_VICTIM_VALUE,
        help_text="Minimum zkb total value for rookie ship/shuttle/corvette victims to avoid sparring exclusion. Pods are exempt.",
    )
    awox_blue_scouting_bonus = models.PositiveIntegerField(
        default=DEFAULT_AWOX_BLUE_SCOUTING_BONUS,
        help_text="Score bonus per kill qualified via the blue-scouting path (NPC-corp alt + main/other alts share corp/alliance with victim).",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = []
        permissions = [
            ("view_dashboard", "Can view security audit dashboard"),
            ("view_summaries", "Can view security audit summaries"),
            ("run_audit", "Can run manual security audits"),
            ("administrate", "Can administrate security audits"),
            ("generate_link", "Can generate shareable security audit summary links"),
            ("manage_enemies", "Can manage security audit enemy lists"),
            ("view_enemies", "Can view security audit enemy lists"),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        policy, _ = cls.objects.get_or_create(name="default")
        return policy


class EnemyEntity(models.Model):
    TYPE_ALLIANCE = "alliance"
    TYPE_CORP = "corporation"
    TYPE_CHARACTER = "character"
    ENTITY_TYPE_CHOICES = [
        (TYPE_ALLIANCE, "Alliance"),
        (TYPE_CORP, "Corporation"),
        (TYPE_CHARACTER, "Character"),
    ]

    entity_type = models.CharField(max_length=16, choices=ENTITY_TYPE_CHOICES)
    entity_id = models.BigIntegerField()
    label = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="securityaudit_enemy_entries",
    )

    class Meta:
        default_permissions = []
        unique_together = ("entity_type", "entity_id")
        indexes = [models.Index(fields=["entity_type", "entity_id", "is_active"])]

    def __str__(self):
        if self.label:
            return f"{self.label} ({self.entity_type}:{self.entity_id})"
        return f"{self.entity_type}:{self.entity_id}"


class FinancialException(models.Model):
    TYPE_CHARACTER = "character"
    TYPE_CORPORATION = "corporation"
    ENTITY_TYPE_CHOICES = [
        (TYPE_CHARACTER, "Character"),
        (TYPE_CORPORATION, "Corporation"),
    ]

    entity_type = models.CharField(max_length=16, choices=ENTITY_TYPE_CHOICES)
    entity_id = models.BigIntegerField()
    label = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="securityaudit_financial_exceptions",
    )

    class Meta:
        default_permissions = []
        unique_together = ("entity_type", "entity_id")
        indexes = [models.Index(fields=["entity_type", "entity_id", "is_active"])]

    def __str__(self):
        if self.label:
            return f"{self.label} ({self.entity_type}:{self.entity_id})"
        return f"{self.entity_type}:{self.entity_id}"


class AuditTarget(models.Model):
    TARGET_INDIVIDUAL = "individual"
    TARGET_CORP = "corporation"
    TARGET_TYPE_CHOICES = [
        (TARGET_INDIVIDUAL, "Individual"),
        (TARGET_CORP, "Corporation"),
    ]

    target_type = models.CharField(max_length=16, choices=TARGET_TYPE_CHOICES)
    character_name = models.CharField(max_length=128, blank=True)
    character_id = models.BigIntegerField(null=True, blank=True)
    corp_id = models.BigIntegerField(null=True, blank=True)
    corp_name = models.CharField(max_length=128, blank=True)

    class Meta:
        default_permissions = []
        indexes = [models.Index(fields=["target_type", "character_name", "corp_id"])]

    def __str__(self):
        if self.target_type == self.TARGET_INDIVIDUAL:
            return self.character_name or str(self.character_id)
        return self.corp_name or str(self.corp_id)


class AuditRun(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETE = "complete"
    STATUS_INCOMPLETE_MISSING_SCOPES = "incomplete_missing_scopes"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_INCOMPLETE_MISSING_SCOPES, "Incomplete (Missing Scopes)"),
        (STATUS_FAILED, "Failed"),
    ]

    target = models.ForeignKey(AuditTarget, on_delete=models.CASCADE, related_name="runs")
    parent_run = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_runs",
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="securityaudit_runs",
    )
    automated = models.BooleanField(default=False)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    risk_score = models.PositiveIntegerField(default=0)
    risk_level = models.CharField(max_length=16, default="low")
    summary = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    missing_scopes = models.TextField(blank=True)
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=100)
    progress_message = models.CharField(max_length=255, blank=True, default="")
    progress_details = models.JSONField(default=dict, blank=True)
    policy_overrides = models.JSONField(default=dict, blank=True)
    task_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = []
        indexes = [
            models.Index(fields=["status", "automated", "created_at"]),
            models.Index(fields=["risk_level", "created_at"]),
        ]

    def __str__(self):
        return f"AuditRun #{self.pk} ({self.target})"

    def set_running(self):
        self.status = self.STATUS_RUNNING
        if not self.started_at:
            self.started_at = timezone.now()
        self.progress_current = 5
        self.progress_total = 100
        self.progress_message = "Initializing audit"
        self.save(update_fields=["status", "started_at", "progress_current", "progress_total", "progress_message"])

    def set_progress(self, current, total=100, message="", details=None):
        if total <= 0:
            total = 100
        if current < 0:
            current = 0
        if current > total:
            current = total
        self.progress_current = int(current)
        self.progress_total = int(total)
        self.progress_message = (message or "")[:255]
        if details is not None:
            self.progress_details = details or {}
        update_fields = ["progress_current", "progress_total", "progress_message"]
        if details is not None:
            update_fields.append("progress_details")
        self.save(update_fields=update_fields)

    @property
    def progress_percent(self):
        if self.progress_total <= 0:
            return 0
        return int((self.progress_current / self.progress_total) * 100)

    def mark_complete(self, summary="", risk_score=0, risk_level="low"):
        self.status = self.STATUS_COMPLETE
        self.summary = summary
        self.risk_score = risk_score
        self.risk_level = risk_level
        self.finished_at = timezone.now()
        self.error_message = ""
        self.missing_scopes = ""
        self.progress_current = self.progress_total
        self.progress_message = "Audit complete"
        self.save(
            update_fields=[
                "status",
                "summary",
                "risk_score",
                "risk_level",
                "finished_at",
                "error_message",
                "missing_scopes",
                "progress_current",
                "progress_message",
            ]
        )

    def mark_incomplete_missing_scopes(self, scopes, message=""):
        self.status = self.STATUS_INCOMPLETE_MISSING_SCOPES
        self.missing_scopes = ",".join(sorted(set(scopes)))
        self.error_message = message
        self.finished_at = timezone.now()
        self.progress_current = self.progress_total
        self.progress_message = "Missing required ESI scopes"
        self.save(
            update_fields=[
                "status",
                "missing_scopes",
                "error_message",
                "finished_at",
                "progress_current",
                "progress_message",
            ]
        )

    def mark_failed(self, message):
        self.status = self.STATUS_FAILED
        self.error_message = message
        self.missing_scopes = ""
        self.finished_at = timezone.now()
        self.progress_current = self.progress_total
        self.progress_message = "Audit failed"
        self.save(
            update_fields=["status", "error_message", "missing_scopes", "finished_at", "progress_current", "progress_message"]
        )

    def reset_to_pending(self):
        self.status = self.STATUS_QUEUED
        self.risk_score = 0
        self.risk_level = "low"
        self.summary = ""
        self.error_message = ""
        self.missing_scopes = ""
        self.progress_current = 0
        self.progress_total = 100
        self.progress_message = ""
        self.progress_details = {}
        self.started_at = None
        self.finished_at = None
        self.task_id = ""
        self.findings.all().delete()
        self.counterparties.all().delete()
        self.capital_ship_observations.all().delete()
        self.save(
            update_fields=[
                "status",
                "risk_score",
                "risk_level",
                "summary",
                "error_message",
                "missing_scopes",
                "progress_current",
                "progress_total",
                "progress_message",
                "progress_details",
                "started_at",
                "finished_at",
                "task_id",
            ]
        )


class AuditFinding(models.Model):
    TYPE_UNDISCLOSED_ALTS = "undisclosed_alts"
    TYPE_SPY_ACTIVITY = "spy_activity"
    TYPE_FLIGHT_RISK = "flight_risk"
    TYPE_UNDISCLOSED_ALT_CORPS = "undisclosed_alt_corps"
    TYPE_ENEMY_CONNECTION = "enemy_connection"
    TYPE_LARGE_DONATION = "large_donation"
    TYPE_PLUS_TEN_STANDING = "plus_ten_standing"
    TYPE_FREE_CONTRACT = "free_contract"
    TYPE_REPEATED_TRANSFERS = "repeated_transfers"
    TYPE_BLACKLIST_ADJACENT = "blacklist_adjacent"
    TYPE_AWOX = "awox"
    TYPE_OTHER = "other"

    FINDING_TYPE_CHOICES = [
        (TYPE_UNDISCLOSED_ALTS, "Undisclosed Alts"),
        (TYPE_SPY_ACTIVITY, "spy_activity"),
        (TYPE_FLIGHT_RISK, "flight_risk"),
        (TYPE_UNDISCLOSED_ALT_CORPS, "Undisclosed Alt Corps"),
        (TYPE_ENEMY_CONNECTION, "Enemy Connection"),
        (TYPE_LARGE_DONATION, "Large Donation"),
        (TYPE_PLUS_TEN_STANDING, "+10 Standing"),
        (TYPE_FREE_CONTRACT, "Free Contract"),
        (TYPE_REPEATED_TRANSFERS, "Repeated Transfers"),
        (TYPE_BLACKLIST_ADJACENT, "Blacklist Adjacent"),
        (TYPE_AWOX, "Awox / Friendly Fire"),
        (TYPE_OTHER, "Other"),
    ]

    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_NONE = "none"
    SEVERITY_CHOICES = [
        (SEVERITY_NONE, "None"),
        (SEVERITY_LOW, "Low"),
        (SEVERITY_MEDIUM, "Medium"),
        (SEVERITY_HIGH, "High"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    audit_run = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="findings")
    finding_type = models.CharField(max_length=48, choices=FINDING_TYPE_CHOICES)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_LOW)
    title = models.CharField(max_length=160)
    details = models.TextField(blank=True)
    score_impact = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = []
        indexes = [models.Index(fields=["finding_type", "severity"])]

    def __str__(self):
        return f"{self.finding_type} ({self.severity})"


class AuditEvidence(models.Model):
    finding = models.ForeignKey(AuditFinding, on_delete=models.CASCADE, related_name="evidence")
    key = models.CharField(max_length=128)
    value = models.TextField()
    observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = []
        indexes = [models.Index(fields=["key"])]

    def __str__(self):
        return f"{self.key}={self.value[:48]}"


class AuditRelationshipCounterparty(models.Model):
    COUNTERPARTY_ISK_DONATION = "isk_donation"
    COUNTERPARTY_PLUS_TEN = "plus_ten_standing"
    COUNTERPARTY_FREE_CONTRACT = "free_contract"
    COUNTERPARTY_OTHER = "other"
    COUNTERPARTY_POSSIBLE_ALT = "possible_alt"

    COUNTERPARTY_TYPE_CHOICES = [
        (COUNTERPARTY_ISK_DONATION, "ISK Donation"),
        (COUNTERPARTY_PLUS_TEN, "+10 Standing"),
        (COUNTERPARTY_FREE_CONTRACT, "Free Contract"),
        (COUNTERPARTY_POSSIBLE_ALT, "Possible Alt"),
        (COUNTERPARTY_OTHER, "Other"),
    ]

    audit_run = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="counterparties")
    counterparty_type = models.CharField(max_length=32, choices=COUNTERPARTY_TYPE_CHOICES)
    character_id = models.BigIntegerField(null=True, blank=True)
    character_name = models.CharField(max_length=128, blank=True)
    total_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0"))
    is_outgoing = models.BooleanField(default=False, help_text="True if the target sent ISK to this counterparty.")
    event_count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        default_permissions = []
        indexes = [
            models.Index(fields=["counterparty_type", "character_id"]),
            models.Index(fields=["total_amount"]),
        ]

    def __str__(self):
        return f"{self.counterparty_type}:{self.character_name or self.character_id}"


class AuditCapitalShipObservation(models.Model):
    CATEGORY_CARRIER = "carrier"
    CATEGORY_DREAD = "dread"
    CATEGORY_FAX = "fax"
    CATEGORY_SUPERCARRIER = "supercarrier"
    CATEGORY_TITAN = "titan"
    CATEGORY_CHOICES = [
        (CATEGORY_CARRIER, "Carrier"),
        (CATEGORY_DREAD, "Dreadnought"),
        (CATEGORY_FAX, "Force Auxiliary"),
        (CATEGORY_SUPERCARRIER, "Supercarrier"),
        (CATEGORY_TITAN, "Titan"),
    ]

    audit_run = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="capital_ship_observations")
    character_id = models.BigIntegerField()
    character_name = models.CharField(max_length=128, blank=True, default="")
    ship_type_id = models.BigIntegerField()
    ship_name = models.CharField(max_length=128, blank=True, default="")
    ship_category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    observation_count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    asset_count = models.PositiveIntegerField(default=0)
    is_current_ship = models.BooleanField(default=False)
    contract_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of active contracts involving this capital ship type.",
    )
    market_order_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of active sell orders for this capital ship type.",
    )

    class Meta:
        default_permissions = []
        unique_together = ("audit_run", "character_id", "ship_type_id")
        indexes = [models.Index(fields=["ship_category"])]

    def __str__(self):
        return f"{self.ship_name} ({self.character_name})"


class AuditSummaryView(models.Model):
    audit_run = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="summary_views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = []
        unique_together = ["audit_run", "user"]

    def __str__(self):
        return f"View by {self.user} on {self.audit_run}"


class AuditSummaryLink(models.Model):
    audit_run = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="summary_links")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="securityaudit_summary_links",
    )
    token = models.CharField(max_length=64, unique=True, default=_generate_summary_token, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = []
        indexes = [models.Index(fields=["token"])]

    def __str__(self):
        return f"Summary link for {self.audit_run}"
