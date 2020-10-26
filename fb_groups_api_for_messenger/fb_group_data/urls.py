from django.urls import path

from . import views

app_name = 'fb_group_data'

urlpatterns = [
    path('fb_login_redirect', views.fb_login_redirect, name='fb_login_redirect'),
    path('', views.home, name='home'),
    path('group/<int:group_id>', views.group, name='group'),
    path('group/<int:group_id>/weekly_summary?group_name=<str:group_name>'
         '&format=<str:resp_format>', views.group_weekly_summary,
         name='group_weekly_summary'),
]
