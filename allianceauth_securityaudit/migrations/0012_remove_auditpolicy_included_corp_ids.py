from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("securityaudit", "0011_summary_link_expiry_hours"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="auditpolicy",
            name="included_corp_ids",
        ),
    ]
