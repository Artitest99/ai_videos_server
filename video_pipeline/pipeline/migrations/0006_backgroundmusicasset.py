import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0005_videojob_music_track"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackgroundMusicAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("track_id", models.PositiveIntegerField(unique=True)),
                ("display_name", models.CharField(max_length=120)),
                ("original_filename", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["track_id"]},
        ),
    ]
