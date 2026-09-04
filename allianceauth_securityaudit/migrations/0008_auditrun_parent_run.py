from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0007_auditsummaryview"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="parent_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="child_runs",
                to="securityaudit.auditrun",
            ),
        ),
    ]
