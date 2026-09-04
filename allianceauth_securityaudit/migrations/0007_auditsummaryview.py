from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0006_auditpolicy_esi_throttle"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditSummaryView",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("viewed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_run",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="summary_views",
                        to="securityaudit.auditrun",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": (("audit_run", "user"),),
            },
        ),
    ]
