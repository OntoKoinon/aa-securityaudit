from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0018_remove_auditrun_use_beta_disclosed_alt_detection"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="auditpolicy",
            name="automation_frequency_minutes",
        ),
        migrations.RemoveField(
            model_name="auditpolicy",
            name="repeated_donation_window_days",
        ),
        migrations.RemoveField(
            model_name="auditpolicy",
            name="repeated_donation_count_threshold",
        ),
        migrations.RemoveField(
            model_name="auditpolicy",
            name="alt_corp_history_min_shared_corps",
        ),
    ]
