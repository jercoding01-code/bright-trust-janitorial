class SecurityHeadersMiddleware:
    """
    Middleware that adds Content-Security-Policy and Permissions-Policy
    headers to all HTTP responses to harden platform security.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # 1. Content-Security-Policy (CSP)
        # Allows self resources, local assets, Google Fonts, and payment frames/scripts/connectors.
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.squareup.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://ik.imagekit.io https://*.imagekit.io; "
            "frame-src 'self' https://js.squareup.com https://connect.squareup.com; "
            "connect-src 'self' https://connect.squareup.com https://connect.squareupsandbox.com;"
        )
        response['Content-Security-Policy'] = csp
        
        # 2. Permissions-Policy
        # Disable unused sensitive Web features (camera, mic, geo, etc.)
        response['Permissions-Policy'] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        
        return response
