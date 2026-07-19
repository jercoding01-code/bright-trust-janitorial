# Security & Operational Release Approval

**Release Version:** `1.0.0`  
**Security Status:** 🥇 **A+ Rated (Observatory Verified)**  
**Sign-off Date:** UTC July 19, 2026

---

## 🔒 1. Cryptographic Nonce CSP Verification
- **Audit Requirement:** Eliminate `'unsafe-inline'` and `'unsafe-eval'` script directives to prevent Cross-Site Scripting (XSS).
- **Design & Verification:**
  * Enabled unique request-specific cryptographic nonces using Django's custom `SecurityHeadersMiddleware`.
  * Dynamic script tags are injected with the nonce attribute matching the HTTP response headers.
  * Verified result: Security scanner returned a perfect **A+** grade.

---

## 🛡️ 2. Rate Limiting Strategy
- **Design Decision:** The custom `@rate_limit` decorator was chosen because:
  1.  **Zero Overhead:** Bypasses the need to install external packages like `django-ratelimit` or configure Django REST Framework (which is not used in this project's server-rendered stack).
  2.  **Atomicity:** Implements atomic increments using Redis-backed cache `cache.add` + `cache.incr` patterns (thread-safe).
  3.  **Reverse-Proxy / Cloudflare Awareness:** Explicitly checks `HTTP_CF_CONNECTING_IP` first to resolve the real client IP (avoiding rate-limiting Cloudflare's edge nodes as a single visitor).
  4.  **Logging Visibility:** Logs every blocked IP at the `WARNING` level with standard logs.

- **Throttling Thresholds:**
  * **Public Booking Submits:** 10 submissions per minute.
  * **Public Availability API:** 30 slot fetches per minute.
  * **Cleaner & Admin Portals Login:** 5 attempts per minute.

---

## 📋 3. Security Sign-off Checklist

- [x] **CSP Enforcement:** Inline and CDN scripts validated via nonces.
- [x] **Secure Cookies:** `SameSite=Lax` and `HttpOnly` active on cookies.
- [x] **Cloudflare IP Mapping:** Connecting headers correctly tracked.
- [x] **Log Masking:** Secrets, credentials, and payment details filtered out.
- [x] **Production Health Monitoring:** Live database status and ISO-8601 timestamps exposed.
