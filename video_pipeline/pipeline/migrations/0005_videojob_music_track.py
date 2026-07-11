from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0004_videojob_render_start_script"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="music_track",
            field=models.CharField(default="1", max_length=40),
        ),
    ]
