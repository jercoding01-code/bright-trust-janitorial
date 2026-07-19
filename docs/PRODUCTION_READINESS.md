# Production Readiness Operational Handbook

This document contains checklists and guidelines to manage, monitor, and deploy the Bright Trust Janitorial web application in a production environment.

---

## 📋 1. Django Production Configuration Checklist
Ensure the following settings are active in your production environment settings variables:
- [x] **`DEBUG = False`**: Hardcoded fallback to `False` in production if not explicitly overridden by environment.
- [x] **`SECRET_KEY`**: Set via Render environment variables. Safe fallback is only provided during building/migration steps.
- [x] **`ALLOWED_HOSTS`**: Configured to accept `brighttrustjanitorial.ca`, `www.brighttrustjanitorial.ca`, and the Render subdomain.
- [x] **`CSRF_TRUSTED_ORIGINS`**: Configured to trust HTTPS domains to allow secure POST actions from forms.
- [x] **HTTPS Redirection**: `SECURE_SSL_REDIRECT = True` is active to force all traffic through SSL.
- [x] **Secure Cookies**: Both `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` are set to `True`.
- [x] **HSTS Policies**: `SECURE_HSTS_SECONDS = 31536000` (1 year), `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`, and `SECURE_HSTS_PRELOAD = True` are active.
- [x] **Referrer Header**: `SECURE_REFERRER_POLICY = 'same-origin'` limits details sent on outgoing page links.
- [x] **Frame Protection**: `X_FRAME_OPTIONS = 'DENY'` prevents clickjacking framing attacks.
- [x] **Content-Type Sniffing**: `SECURE_CONTENT_TYPE_NOSNIFF = True` prevents MIME-sniffing exploits.

---

## 🛠️ 2. Infrastructure & Keys Checklist
Verify that your hosting environments are configured with the following production keys:

| Secret / Config Key | Purpose | Expected Value |
| :--- | :--- | :--- |
| `DATABASE_URL` | Supabase Postgres Connection String | `postgresql://...` |
| `SQUARE_ACCESS_TOKEN` | Merchant payment processing | Live production access token |
| `SQUARE_LOCATION_ID` | Store location matching | Live business location ID |
| `SQUARE_SIGNATURE_KEY` | Webhook verification signature key | Square dashboard signature key |
| `SQUARE_ENVIRONMENT` | Payment target environment | Set to `production` |
| `RESEND_API_KEY` | SMTP outgoing email service | Resend API credential |
| `EMAIL_PORT` | Outgoing email port | `465` (SSL active) |
| `IMAGEKIT_PUBLIC_KEY` | File CDN token | ImageKit dashboard key |
| `IMAGEKIT_PRIVATE_KEY` | File CDN private token | ImageKit private key |
| `IMAGEKIT_URL_ENDPOINT` | CDN domain endpoint | `https://ik.imagekit.io/...` |

---

## 🔒 3. Application Security Controls
- **File Upload Protection:**
  * Files are checked for size limits (**maximum 5MB**).
  * MIME types must be `image/*`.
  * Uploaded filenames are sanitized and mapped to randomized UUID filenames to prevent collision and direct path traversal.
  * Temporary files written to local disk are securely cleaned up inside a `finally` block immediately after upload completion.
- **Webhook Protection:**
  * If `SQUARE_SIGNATURE_KEY` is set, incoming webhooks compute an HMAC-SHA256 signature and match it against the header `x-square-hmacsha256-signature`. Failed matches receive `401 Unauthorized`.
- **Brute-Force & Access:**
  * Admin and cleaner dashboard access points are protected by standard Django Session Authentication and password rules.

---

## 🔄 4. Disaster Recovery & Backup Checklist
*This project delegates database services to Supabase. Implement these policies to ensure continuous operation:*

### Database Backups
*   **Automated Daily Backups:** Supabase automatically schedules daily backups. Ensure backups are enabled on your database tier.
*   **Point-in-Time Recovery (PITR):** Enable PITR on the Supabase dashboard to allow rolling back to specific seconds in case of accidental database purges.

### Disaster Recovery Runbook
1.  **Server Recovery (Render):** If Render crashes, check the build logs. Render maintains automated blue-green deployments (so if a new deployment crashes, the older running container is kept online automatically).
2.  **Database Failover (Supabase):** In case of Supabase failure, verify the status at `status.supabase.com`. Ensure you have a local backup dump of schemas using pg_dump:
    ```bash
    pg_dump -H db.supabase.co -U postgres -d postgres > backup.sql
    ```
3.  **Restore Steps:** To restore a database dump to a new instance:
    ```bash
    psql -h new-db-host -U postgres -d postgres -f backup.sql
    ```

---

## 📊 5. Monitoring & Maintenance
- **Uptime Monitoring:** Set up external checks (e.g. UptimeRobot) pointing to `https://brighttrustjanitorial.ca/health/`.
  * The health check returns `200 OK` JSON if the server and database connections are operational.
  * Returns `500 Internal Server Error` if the database connectivity fails.
- **Log Management:** Django is configured with standard console routing for stdout/stderr logs. Monitor the logs directly in the Render logs dashboard.
