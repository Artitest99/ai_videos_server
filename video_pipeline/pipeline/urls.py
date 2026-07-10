from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('job/<int:job_id>/', views.job_status, name='job_status'),
    path('api/job/<int:job_id>/', views.job_status_api, name='job_status_api'),
    path('download/<int:job_id>/', views.download_video, name='download_video'),  # Add this line
]