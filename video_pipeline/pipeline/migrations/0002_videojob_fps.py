from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="fps",
            field=models.PositiveIntegerField(default=30),
        ),
    ]
