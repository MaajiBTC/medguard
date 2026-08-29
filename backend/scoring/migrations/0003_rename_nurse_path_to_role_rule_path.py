from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scoring", "0002_alter_accessdecision_decision_type_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="accessdecision",
            old_name="nurse_path",
            new_name="role_rule_path",
        ),
        migrations.AlterField(
            model_name="accessdecision",
            name="role_rule_path",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
