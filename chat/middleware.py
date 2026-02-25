class JemiChatSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Keep schema and role model aligned (super_admin + group memberships).
        from . import services
        services.initialize_database()

        # Keep template navbar compatibility with old PHP session keys.
        request.user_id = request.session.get('user_id')
        request.username = request.session.get('username')
        request.user_role = request.session.get('role')
        return self.get_response(request)
