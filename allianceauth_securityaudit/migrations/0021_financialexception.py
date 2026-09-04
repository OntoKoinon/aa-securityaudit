from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0020_auditrun_policy_overrides"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialException",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("character", "Character"), ("corporation", "Corporation")], max_length=16)),
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
                        on_delete=models.SET_NULL,
                        related_name="securityaudit_financial_exceptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "default_permissions": [],
                "unique_together": {("entity_type", "entity_id")},
            },
        ),
        migrations.AddIndex(
            model_name="financialexception",
            index=models.Index(fields=["entity_type", "entity_id", "is_active"], name="securityaudit_fex_430c22_idx"),
        ),
    ]
