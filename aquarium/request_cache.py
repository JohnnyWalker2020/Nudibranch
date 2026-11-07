"""Things worth reading only once per page view, like the app settings.

The cache lives for one request and is thrown away after it. Outside a request (the background worker,
management commands, tests calling code directly) nothing is cached, so values are always fresh there.
"""
from contextvars import ContextVar

_store = ContextVar('nudibranch_request_cache', default=None)


def get(key, make):
    store = _store.get()
    if store is None:
        return make()
    if key not in store:
        store[key] = make()
    return store[key]


def forget(key):
    store = _store.get()
    if store is not None:
        store.pop(key, None)


class RequestCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _store.set({})
        try:
            return self.get_response(request)
        finally:
            _store.reset(token)
