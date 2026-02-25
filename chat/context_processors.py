from .services import is_admin_session, is_super_admin_session


def jemichat_context(request):
    page_name = request.path.rsplit('/', 1)[-1].split('.', 1)[0] or 'index'
    return {
        'session_user_id': request.session.get('user_id'),
        'session_username': request.session.get('username'),
        'session_role': request.session.get('role'),
        'session_is_admin': is_admin_session(request),
        'session_is_super_admin': is_super_admin_session(request),
        'page_name': page_name,
    }
