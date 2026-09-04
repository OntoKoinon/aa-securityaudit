from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0002_alter_auditpolicy_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditrun",
            name="progress_current",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="auditrun",
            name="progress_message",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="auditrun",
            name="progress_total",
            field=models.PositiveIntegerField(default=100),
        ),
    ]
