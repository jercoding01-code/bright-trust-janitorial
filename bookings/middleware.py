"""
bookings/middleware.py

Security & Content-Security-Policy (CSP) Middleware for Bright Trust Janitorial Inc.

Responsibilities
----------------
- Generate a unique 128-bit cryptographic nonce (secrets.token_urlsafe) per HTTP request.
- Attach strict Content-Security-Policy (CSP) headers to all outgoing HTTP responses.
- Restrict script, style, font, image, frame, and connect origins to approved CDNs and APIs
  (Square Canada, ImageKit.io CDN, Google Fonts, FullCalendar V6 CDN).
- Attach Permissions-Policy headers to disable unneeded browser capabilities (camera, mic, geo).

Security Notes
--------------
• Dynamic CSP nonces prevent Cross-Site Scripting (XSS) attacks by verifying inline script tags.
"""

import secrets
from typing import Callable
from django.http import HttpRequest, HttpResponse


class SecurityHeadersMiddleware:
    """HTTP Middleware that injects Content-Security-Policy and Permissions-Policy headers.

    Attributes:
        get_response (Callable[[HttpRequest], HttpResponse]): Next middleware/view handler in chain.
    """
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Processes request, attaches CSP nonce, and injects HTTP security headers.

        Args:
            request (HttpRequest): Incoming HTTP request.

        Returns:
            HttpResponse: Outgoing HTTP response with injected CSP and Permissions headers.
        """
        # Generate a unique cryptographic nonce for this request
        nonce: str = secrets.token_urlsafe(16)
        setattr(request, 'csp_nonce', nonce)

        response: HttpResponse = self.get_response(request)
        
        # 1. Content-Security-Policy (CSP)
        # Allows self resources, local assets, Google Fonts, FullCalendar, and Square payment frames/connectors.
        # Uses the secure nonce to validate inline script executions.
        csp: str = (
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
