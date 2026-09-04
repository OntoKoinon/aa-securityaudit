from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0021_add_view_enemies_permission"),
        ("securityaudit", "0021_financialexception"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditCapitalShipObservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("character_id", models.BigIntegerField()),
                ("character_name", models.CharField(blank=True, default="", max_length=128)),
                ("ship_type_id", models.BigIntegerField()),
                ("ship_name", models.CharField(blank=True, default="", max_length=128)),
                (
                    "ship_category",
                    models.CharField(
                        choices=[
                            ("carrier", "Carrier"),
                            ("dread", "Dreadnought"),
                            ("fax", "Force Auxiliary"),
                            ("supercarrier", "Supercarrier"),
                            ("titan", "Titan"),
                        ],
                        max_length=24,
                    ),
                ),
                ("observation_count", models.PositiveIntegerField(default=0)),
                ("first_seen", models.DateTimeField(blank=True, null=True)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                (
                    "audit_run",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="capital_ship_observations",
                        to="securityaudit.auditrun",
                    ),
                ),
            ],
            options={
                "default_permissions": [],
                "unique_together": {("audit_run", "character_id", "ship_type_id")},
            },
        ),
        migrations.AddIndex(
            model_name="auditcapitalshipobservation",
            index=models.Index(fields=["ship_category"], name="securityaudit_acs_cat_idx"),
        ),
    ]
