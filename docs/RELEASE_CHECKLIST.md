# Production Release Checklist & Rollback Plan

This checklist outlines the pre-flight verification steps and the failover rollback plan to execute when deploying releases to production.

---

## 🚀 Pre-Flight Deploy Checklist

### 1. Infrastructure Checks
- [ ] **DEBUG Configuration:** Verify `DEBUG` is set to `False` in Render dashboard settings.
- [ ] **HTTPS Redirection:** Verify SSL certificate is active on Render. `SECURE_SSL_REDIRECT` will automatically force all HTTP traffic to HTTPS.
- [ ] **Custom Domain:** Verify `brighttrustjanitorial.ca` DNS records point to Render hosts.
- [ ] **Environment Keys:** Verify all production secret environment keys are set correctly.

### 2. Database Controls
- [ ] **Applied Migrations:** Run check commands to ensure migrations are fully synchronized:
  ```bash
  python manage.py showmigrations
  ```
- [ ] **Database Indexes:** Verify indexes on query-intensive columns (`status`, `email`, `requested_date_time`, `requested_end_time`, `created_at`) are built.
- [ ] **Supabase Backups:** Verify Supabase automatic daily database backups are active.

### 3. Third-Party Integrations
- [ ] **Square Live keys:** Verify `SQUARE_ENVIRONMENT` is set to `production` and production merchant access token and location IDs are populated.
- [ ] **Resend Verified Domain:** Verify the domain `brighttrustjanitorial.ca` is marked as active inside the Resend settings console.
- [ ] **ImageKit API:** Verify CDN endpoints are active.

### 4. Security Enforcement
- [ ] **Cookie Security:** Verify cookies are flagged as secure (`SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SameSite=Lax`).
- [ ] **Middleware Headers:** Verify `SecurityHeadersMiddleware` is active and sets strict `Content-Security-Policy` and `Permissions-Policy` headers.
- [ ] **File Uploader Limits:** Verify uploads > 5MB and non-image extensions are blocked.
- [ ] **Rate Limiting:** Verify brute-force protection throttles public endpoints.

### 5. Monitoring
- [ ] **Uptime Checker:** Verify Uptime status checks point to the enhanced `/health/` endpoint.
- [ ] **Render Log Streams:** Verify standard console logs filter Django actions and custom database warnings to stderr/stdout.

---

## 🔄 Emergency Rollback Plan

If a critical incident occurs during or immediately after deployment (e.g. database connection failures, fatal server crashes, broken payment processing), execute the following rollback runbook:

### Step 1: Revert Render Deployment
1.  Log in to the **Render Dashboard**.
2.  Select the **Bright Trust Janitorial** web service.
3.  Navigate to the **Events** tab.
4.  Locate the last successful stable commit release.
5.  Click the menu next to it and select **Rollback to this deploy**.
6.  Render will instantly deploy the previous docker image, bringing the server back to a stable state within ~1–2 minutes.

### Step 2: Database Migration Reversion
If the new release introduced database schema changes that are incompatible with the rolled-back server code:
1.  Check the database migration history using command line terminal:
    ```bash
    python manage.py showmigrations
    ```
2.  Roll back the database schema to the last compatible migration index (e.g., target `0015` if `0016` caused a crash):
    ```bash
    python manage.py migrate bookings 0015
    ```
3.  If severe database corruption occurred, navigate to the **Supabase Dashboard**, select **Database Backups**, locate the last daily backup, and click **Restore**.

### Step 3: Verification Post-Rollback
1.  Verify the `/health/` endpoint returns `200 OK` status.
2.  Check Render logs for any remaining `500` or connection errors.
3.  Perform a manual booking flow test to confirm database write integrity is restored.
