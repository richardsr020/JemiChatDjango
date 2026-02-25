from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from chat import views

urlpatterns = [
    path('', views.root_redirect, name='root'),
    path('index.php', views.index_view, name='index_php'),
    path('login.php', views.login_view, name='login_php'),
    path('register.php', views.register_view, name='register_php'),
    path('logout.php', views.logout_view, name='logout_php'),
    path('send_message.php', views.send_message_view, name='send_message_php'),
    path('edit_message.php', views.edit_message_view, name='edit_message_php'),
    path('delete_message.php', views.delete_message_view, name='delete_message_php'),
    path('upload.php', views.upload_view, name='upload_php'),
    path('download.php', views.download_view, name='download_php'),
    path('view_file.php', views.view_file_view, name='view_file_php'),
    path('delete.php', views.delete_file_view, name='delete_file_php'),
    path('profile.php', views.profile_view, name='profile_php'),
    path('admin.php', views.admin_view, name='admin_php'),
]

urlpatterns += staticfiles_urlpatterns()
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
