from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0013_auditrun_progress_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="task_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
