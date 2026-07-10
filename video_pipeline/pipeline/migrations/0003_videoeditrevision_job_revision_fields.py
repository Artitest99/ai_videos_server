import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0002_videojob_fps"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="current_revision",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="videojob",
            name="render_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="videojob",
            name="rendered_revision",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="VideoEditRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("snapshot", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edit_revisions", to="pipeline.videojob")),
            ],
            options={"ordering": ["-number"]},
        ),
        migrations.AddConstraint(
            model_name="videoeditrevision",
            constraint=models.UniqueConstraint(fields=("job", "number"), name="unique_job_edit_revision"),
        ),
    ]
