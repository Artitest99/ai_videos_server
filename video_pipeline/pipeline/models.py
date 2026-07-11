from django.db import models
from django.utils import timezone

class VideoJob(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    file_name = models.CharField(max_length=255)
    fps = models.PositiveIntegerField(default=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_script = models.CharField(max_length=255, blank=True)
    progress = models.IntegerField(default=0)
    log = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    current_revision = models.PositiveIntegerField(default=0)
    rendered_revision = models.PositiveIntegerField(default=0)
    render_required = models.BooleanField(default=False)
    render_start_script = models.CharField(max_length=80, default="create_video.py")
    music_track = models.CharField(max_length=40, default="1")
    
    def __str__(self):
        return f"{self.file_name} - {self.status}"


class VideoEditRevision(models.Model):
    job = models.ForeignKey(VideoJob, on_delete=models.CASCADE, related_name="edit_revisions")
    number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["job", "number"], name="unique_job_edit_revision"),
        ]

    def __str__(self):
        return f"{self.job.file_name} revision {self.number}"


class BackgroundMusicAsset(models.Model):
    track_id = models.PositiveIntegerField(unique=True)
    display_name = models.CharField(max_length=120)
    original_filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["track_id"]

    def __str__(self):
        return self.display_name
