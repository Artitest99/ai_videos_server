from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('job/<int:job_id>/', views.job_status, name='job_status'),
    path('api/job/<int:job_id>/', views.job_status_api, name='job_status_api'),
    path('download/<int:job_id>/', views.download_video, name='download_video'),
    path('watch/<int:job_id>/', views.watch_video, name='watch_video'),
    path('job/<int:job_id>/retry/', views.retry_job, name='retry_job'),
    path('job/<int:job_id>/edit/', views.edit_job, name='edit_job'),
    path('job/<int:job_id>/edit/render/', views.render_edits, name='render_edits'),
    path('job/<int:job_id>/scene/<int:scene_index>/media/', views.scene_media, name='scene_media'),
]
