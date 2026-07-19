from django.core.cache import cache
from django.http import HttpResponse
from functools import wraps

def rate_limit(limit=10, period=60):
    """
    Lightweight rate limiting decorator using Django's Cache framework.
    Allows up to 'limit' requests per client IP address in 'period' seconds.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Resolve client IP address behind proxy / load balancer
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
                
            cache_key = f"rate_limit_{view_func.__name__}_{ip}"
            request_count = cache.get(cache_key, 0)
            
            if request_count >= limit:
                return HttpResponse(
                    "Too many requests. Please wait before submitting again.",
                    status=429,
                    content_type="text/plain"
                )
                
            cache.set(cache_key, request_count + 1, period)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
