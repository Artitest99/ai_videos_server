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
    
    def __str__(self):
        return f"{self.file_name} - {self.status}"
