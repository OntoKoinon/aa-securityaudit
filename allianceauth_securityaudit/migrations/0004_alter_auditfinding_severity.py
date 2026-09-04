from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0003_auditrun_progress_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditfinding",
            name="severity",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("low", "Low"),
                    ("medium", "Medium"),
                    ("high", "High"),
                    ("critical", "Critical"),
                ],
                default="low",
                max_length=16,
            ),
        ),
    ]
