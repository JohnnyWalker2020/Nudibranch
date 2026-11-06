"""Requires a signed-in user for the whole app, apart from what a browser or device needs before signing in."""
import hmac
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

# Static files are served before this runs. /admin/ has its own sign-in, for staff only.
PUBLIC_PREFIXES = ('/login/', '/setup/', '/static/', '/admin/')
PUBLIC_PATHS = ('/sw.js', '/favicon.ico')
# This endpoint checks the API key itself.
KEY_CHECKED_PATHS = ('/api/parameters/log/',)
# This one also works for a device holding the key.
KEY_ALLOWED_PATHS = ('/api/parameters/types/',)


def has_valid_api_key(request):
    expected = getattr(settings, 'API_SECRET_KEY', '')
    if not expected:
        return False
    supplied = request.headers.get('X-API-Key') or ''
    authorization = request.headers.get('Authorization') or ''
    if authorization.startswith('Bearer '):
        supplied = authorization.split('Bearer ', 1)[1].strip()
    return hmac.compare_digest(supplied.encode(), expected.encode())


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'LOGIN_REQUIRED', True) or self._is_allowed(request):
            return self.get_response(request)
        if request.path.startswith('/api/'):
            return JsonResponse({'error': 'Sign in or provide a valid API key.'}, status=401)
        if not get_user_model().objects.exists():
            target = reverse('setup')
        else:
            target = f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}"
        if request.headers.get('HX-Request'):
            response = HttpResponse(status=401)
            response['HX-Redirect'] = target
            return response
        return redirect(target)

    def _is_allowed(self, request):
        path = request.path
        if request.user.is_authenticated or path in PUBLIC_PATHS or path in KEY_CHECKED_PATHS:
            return True
        if path.startswith(PUBLIC_PREFIXES):
            return True
        return path in KEY_ALLOWED_PATHS and has_valid_api_key(request)
