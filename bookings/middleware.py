import secrets

class SecurityHeadersMiddleware:
    """
    Middleware that adds Content-Security-Policy and Permissions-Policy
    headers to all HTTP responses to harden platform security.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate a unique cryptographic nonce for this request
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce

        response = self.get_response(request)
        
        # 1. Content-Security-Policy (CSP)
        # Allows self resources, local assets, Google Fonts, and payment frames/scripts/connectors.
        # Uses the secure nonce to validate inline scripts.
        csp = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://js.squareup.com https://cdn.jsdelivr.net; "
            f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            f"font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            f"img-src 'self' data: https://ik.imagekit.io https://*.imagekit.io; "
            f"frame-src 'self' https://js.squareup.com https://connect.squareup.com; "
            f"connect-src 'self' https://connect.squareup.com https://connect.squareupsandbox.com;"
        )
        response['Content-Security-Policy'] = csp
        
        # 2. Permissions-Policy
        # Disable unused sensitive Web features (camera, mic, geo, etc.)
        response['Permissions-Policy'] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        
        return response
