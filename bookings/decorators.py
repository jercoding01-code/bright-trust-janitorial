from django.core.cache import cache
from django.http import HttpResponse
from functools import wraps
import logging

logger = logging.getLogger('bookings')

def rate_limit(limit=10, period=60):
    """
    Lightweight rate limiting decorator using Django's Cache framework.
    Supports atomic counters, Cloudflare IP detection, and security logging.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 1. Resolve client IP behind Cloudflare and standard proxies
            cf_connecting_ip = request.META.get('HTTP_CF_CONNECTING_IP')
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            
            if cf_connecting_ip:
                ip = cf_connecting_ip.strip()
            elif x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
                
            cache_key = f"rate_limit_{view_func.__name__}_{ip}"
            
            # 2. Atomic counter increment
            # Set to 0 only if key does not exist (does not overwrite existing values)
            cache.add(cache_key, 0, period)
            request_count = cache.incr(cache_key)
            
            if request_count > limit:
                logger.warning(
                    f"Rate limit exceeded: IP {ip} blocked on '{view_func.__name__}' "
                    f"(Requests: {request_count}/{limit} in {period}s)"
                )
                return HttpResponse(
                    "Too many requests. Please wait before submitting again.",
                    status=429,
                    content_type="text/plain"
                )
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
