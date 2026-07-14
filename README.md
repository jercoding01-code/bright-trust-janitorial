# Bright Trust Janitorial

A production-ready, fully responsive booking and service management Django application designed for janitorial and cleaning services. It decouples media persistence and database storage to scale cleanly on platforms like Render, utilizing Supabase PostgreSQL and ImageKit.io for automatic image optimization.

---

## Technical Stack & Decoupled Architecture

- **Backend:** Django (Python 3.12)
- **Database:** Supabase PostgreSQL (decoupled with PgBouncer connection pooling)
- **Media Asset Storage:** ImageKit.io (direct backend-intercepted uploads, dynamic `q-auto`, `f-auto` WebP optimizations)
- **Production Server:** Render (Free Tier Web Service utilizing a custom `build.sh` script)
- **Email System:** SMTP with inline HTML brand logo attachments, Square Canada payment buttons, and plain-text fallback generators.

---

## Core Features & Workflows

### 1. Customer Booking Flow
* Access at `/book/`.
* Allows uploading up to **4 property photos**. The files are intercepted on the backend, uploaded to ImageKit.io via the official Python SDK, and stored in the database `photos_log` table.
* Baseline price estimate is calculated automatically based on square footage.

### 2. Owner / Manager Dashboard
* Access at `/dashboard/login/`.
* Tracks total page views and unique visitors anonymously.
* Real-time search queries and status filtering (New Request, Quote Sent, Scheduled, Completed, Cancelled).
* Configure business settings (base fee, multiplier, cleaner PIN, Square Canada payment link).
* Secure profile management (change password, username, email) directly inside the settings tab.

### 3. Mobile Cleaner Portal
* Access at `/cleaner/login/` via a 4-digit PIN.
* Cleaners view their active scheduled assignments.
* Upload a completion photo directly from their camera. The backend uploads this image to ImageKit, logs the photo in the database, sets status to `COMPLETED`, and dispatches the customer invoice email automatically.

---

## Setup & Local Installation

1. Activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # Unix/macOS
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run migrations (falls back to local SQLite):
   ```bash
   python manage.py migrate
   ```
4. Start the server:
   ```bash
   python manage.py runserver
   ```
5. View at **http://127.0.0.1:8000/**.

---

## Production Deployment (Render)

1. Map the environment variables in your Render Web Service:
   - `DATABASE_URL` (Supabase PgBouncer URI)
   - `IMAGEKIT_PUBLIC_KEY`
   - `IMAGEKIT_PRIVATE_KEY`
   - `IMAGEKIT_URL_ENDPOINT`
2. Change the **Build Command** to: `./build.sh`
3. Change the **Start Command** to: `gunicorn BrightTrustJanitorial.wsgi:application`
