from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0003_videoeditrevision_job_revision_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="render_start_script",
            field=models.CharField(default="create_video.py", max_length=80),
        ),
    ]
