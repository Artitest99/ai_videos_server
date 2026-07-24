from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0006_backgroundmusicasset"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="voice_key",
            field=models.CharField(default="Rachel_other", max_length=40),
        ),
    ]
