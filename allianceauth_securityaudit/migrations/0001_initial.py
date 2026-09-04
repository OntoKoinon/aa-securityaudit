from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="default", max_length=64, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("automation_enabled", models.BooleanField(default=True)),
                ("automation_frequency_minutes", models.PositiveIntegerField(default=60)),
                ("new_join_window_days", models.PositiveIntegerField(default=14)),
                (
                    "included_corp_ids",
                    models.TextField(blank=True, default="", help_text="Comma-separated corp IDs for automation scope."),
                ),
                (
                    "large_donation_isk_threshold",
                    models.DecimalField(decimal_places=2, default=Decimal("1000000000"), max_digits=20),
                ),
                (
                    "free_contract_value_threshold",
                    models.DecimalField(decimal_places=2, default=Decimal("500000000"), max_digits=20),
                ),
                ("corp_hop_window_days", models.PositiveIntegerField(default=90)),
                ("corp_hop_count_threshold", models.PositiveIntegerField(default=3)),
                ("repeated_donation_window_days", models.PositiveIntegerField(default=30)),
                ("repeated_donation_count_threshold", models.PositiveIntegerField(default=3)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "permissions": [
                    ("view_dashboard", "Can view security audit dashboard"),
                    ("run_audit", "Can run manual security audits"),
                    ("manage_policy", "Can manage security audit policy"),
                    ("manage_enemies", "Can manage security audit enemy lists"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AuditTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "target_type",
                    models.CharField(
                        choices=[("individual", "Individual"), ("corporation", "Corporation")],
                        max_length=16,
                    ),
                ),
                ("character_name", models.CharField(blank=True, max_length=128)),
                ("character_id", models.BigIntegerField(blank=True, null=True)),
                ("corp_id", models.BigIntegerField(blank=True, null=True)),
                ("corp_name", models.CharField(blank=True, max_length=128)),
            ],
        ),
        migrations.CreateModel(
            name="EnemyEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "entity_type",
                    models.CharField(
                        choices=[
                            ("alliance", "Alliance"),
                            ("corporation", "Corporation"),
                            ("character", "Character"),
                        ],
                        max_length=16,
                    ),
                ),
                ("entity_id", models.BigIntegerField()),
                ("label", models.CharField(blank=True, max_length=128)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="securityaudit_enemy_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("entity_type", "entity_id")}},
        ),
        migrations.CreateModel(
            name="AuditRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("automated", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("incomplete_missing_scopes", "Incomplete (Missing Scopes)"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=40,
                    ),
                ),
                ("risk_score", models.PositiveIntegerField(default=0)),
                ("risk_level", models.CharField(default="low", max_length=16)),
                ("summary", models.TextField(blank=True)),
                ("error_message", models.TextField(blank=True)),
                ("missing_scopes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="securityaudit_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "target",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="securityaudit.audittarget"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AuditFinding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "finding_type",
                    models.CharField(
                        choices=[
                            ("undisclosed_alts", "Undisclosed Alts"),
                            ("spy_activity", "Spy-like Activity"),
                            ("undisclosed_alt_corps", "Undisclosed Alt Corps"),
                            ("enemy_connection", "Enemy Connection"),
                            ("large_donation", "Large Donation"),
                            ("plus_ten_standing", "+10 Standing"),
                            ("free_contract", "Free Contract"),
                            ("repeated_transfers", "Repeated Transfers"),
                            ("other", "Other"),
                        ],
                        max_length=48,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        default="low",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                ("details", models.TextField(blank=True)),
                ("score_impact", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_run",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="findings", to="securityaudit.auditrun"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=128)),
                ("value", models.TextField()),
                ("observed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "finding",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence", to="securityaudit.auditfinding"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AuditRelationshipCounterparty",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "counterparty_type",
                    models.CharField(
                        choices=[
                            ("isk_donation", "ISK Donation"),
                            ("plus_ten_standing", "+10 Standing"),
                            ("free_contract", "Free Contract"),
                            ("other", "Other"),
                        ],
                        max_length=32,
                    ),
                ),
                ("character_id", models.BigIntegerField(blank=True, null=True)),
                ("character_name", models.CharField(blank=True, max_length=128)),
                ("total_amount", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=20)),
                ("event_count", models.PositiveIntegerField(default=0)),
                ("first_seen", models.DateTimeField(blank=True, null=True)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                (
                    "audit_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="counterparties",
                        to="securityaudit.auditrun",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="audittarget",
            index=models.Index(fields=["target_type", "character_name", "corp_id"], name="securityaudi_target__f329e5_idx"),
        ),
        migrations.AddIndex(
            model_name="enemyentity",
            index=models.Index(fields=["entity_type", "entity_id", "is_active"], name="securityaudi_entity__3fba50_idx"),
        ),
        migrations.AddIndex(
            model_name="auditrun",
            index=models.Index(fields=["status", "automated", "created_at"], name="securityaudi_status_78d20c_idx"),
        ),
        migrations.AddIndex(
            model_name="auditrun",
            index=models.Index(fields=["risk_level", "created_at"], name="securityaudi_risk_le_d95642_idx"),
        ),
        migrations.AddIndex(
            model_name="auditfinding",
            index=models.Index(fields=["finding_type", "severity"], name="securityaudi_finding_44d6a1_idx"),
        ),
        migrations.AddIndex(
            model_name="auditevidence",
            index=models.Index(fields=["key"], name="securityaudi_key_91afc7_idx"),
        ),
        migrations.AddIndex(
            model_name="auditrelationshipcounterparty",
            index=models.Index(fields=["counterparty_type", "character_id"], name="securityaudi_counter_b52423_idx"),
        ),
        migrations.AddIndex(
            model_name="auditrelationshipcounterparty",
            index=models.Index(fields=["total_amount"], name="securityaudi_total_a_31fddb_idx"),
        ),
    ]
