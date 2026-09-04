from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0017_auditrun_use_beta_disclosed_alt_detection"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="auditrun",
            name="use_beta_disclosed_alt_detection",
        ),
    ]
