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

## 🔄 4. Backup & Disaster Recovery Operations

### Database Backup Properties (Supabase)
- **Backup Retention:** Supabase retains daily backups for 7 days (Free Tier) or 30 days (Pro Tier). PITR (Point-in-Time Recovery) enables rolling back to any given point within the retention window.
- **Verification Plan:** Download database backups monthly and restore them to a local Docker instance to verify table schema integrity and record accuracy.
- **Recovery Point Objective (RPO):** Maximum 24 hours (with daily backups) or 5 minutes (with PITR active).
- **Recovery Time Objective (RTO):** Under 30 minutes to spin up a failover instance and restore the schema and data.

### Disaster Recovery Restore Procedure
1.  Verify the integrity of your backup file (`backup.sql`).
2.  If the production host is unresponsive, provision a new Supabase PostgreSQL instance.
3.  Set the new connection host URL in Render under `DATABASE_URL`.
4.  Restore the schema and records from the command line:
    ```bash
    psql -h new-supabase-host.supabase.co -U postgres -d postgres -f backup.sql
    ```
5.  Re-run migration verification scripts to confirm column hashes:
    ```bash
    python manage.py migrate --check
    ```

---

## 💳 5. End-to-End Payment Workflow & Verification

The transactional pipeline is designed to be fully idempotent and self-healing:

1.  **Booking Request:** Customer books a slot; record status is set to `NEW` with an auto-calculated estimate.
2.  **Quote Dispatch:** Admin reviews request and sets `final_quote_price`. Tapping "Send Email" fires Resend SMTP mail with a dynamic Square Online Checkout invoice link for a 25% downpayment deposit. Record status is updated to `CONTACTED`.
3.  **Customer Payment:** Customer pays. Square triggers a webhook event.
4.  **Signature Checking:** The endpoint `square_webhook` computes HMAC-SHA256 signature and validates origin.
5.  **Idempotency & Replay Protection:**
    *   The webhook updates lead status only if it is in `['NEW', 'CONTACTED']`. If it is already `SCHEDULED` (processed earlier), it is safely skipped.
    *   If payload lacks a direct client ID, the webhook automatically queries Square connect APIs to fetch order details and resolve `reference_id` dynamically.
6.  **Calendar Lock:** Transitioning to `SCHEDULED` locks out other clients from selecting this slot.

---

## 📊 6. Monitoring & Maintenance
- **Uptime Monitoring:** Configure an uptime checker (e.g. UptimeRobot) targeting `https://brighttrustjanitorial.ca/health/` every 5 minutes.
- **Log Management:** Logging configuration captures output at `INFO` level. Filter by loggers `django`, `bookings`, `payments`, `webhooks`, and `emails` inside your Render logs console.
