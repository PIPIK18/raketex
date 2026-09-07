# RAKETEX

## Google Analytics

Google Analytics uses measurement ID `G-VZ21P594BP`. The shared template includes
`templates/analytics.html`, with consent handling in `assets/analytics.js`.
No extra environment variables are needed. Deploy these files with the app.

Analytics loads only after the visitor selects **Accept analytics**. The choice
is remembered for 180 days when browser storage is available. **Cookie settings**
allows visitors to change it; rejecting after accepting disables tracking, clears
GA cookies, and reloads the page to unload the Google library. Analytics records
the home and post pages only, excluding administrators, login, and editing pages.
Advertising consent stays denied. Visitors who reject analytics are not counted.

After deployment, visit the public home page while logged out of the admin account,
accept analytics, and check Google Analytics **Realtime**. Allow up to 30 minutes
for initial collection. A browser blocker can prevent the tag from loading.
Rejecting analytics should produce no requests to Google Analytics or Tag Manager
on subsequent page loads. This measures new traffic from installation onward.

RAKETEX is a Flask app. It is set up to run locally with SQLite/local uploads and on Vercel with Postgres/Vercel Blob for persistent shared posts and images.

## Local run

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Admin login defaults:

```text
username: admin
password: raketex123
```

## Local persistence

Posts are stored in SQLite:

```text
instance/raketex.db
```

Uploaded images are stored in:

```text
instance/uploads/
```

## Vercel deployment

1. Import this GitHub repo into Vercel.
2. In Vercel Storage, create/connect a Marketplace Postgres database, preferably Neon.
3. Create/connect a Vercel Blob store with public access for uploaded images.
4. Confirm these environment variables exist in the Vercel project:

```text
DATABASE_URL or POSTGRES_URL
BLOB_READ_WRITE_TOKEN
RAKETEX_SECRET_KEY
RAKETEX_ADMIN_USER
RAKETEX_ADMIN_PASSWORD
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI
```

`RAKETEX_SECRET_KEY` should be a long random value. `RAKETEX_ADMIN_PASSWORD` replaces the local default password.

If your Blob store is private, the app will upload images privately and serve them through Flask at `/blob/...`. Public Blob stores use direct public Blob URLs.

For Google sign-in, create OAuth credentials in Google Cloud Console and add this authorized redirect URI:

```text
https://your-site.vercel.app/auth/google/callback
```

Vercel recognizes `app.py` as a Flask entrypoint, so no static `index.html` is needed.

## Optional local production-like run

To test with hosted storage locally, pull Vercel environment variables and run the app:

```text
vercel env pull
python app.py
```

Without Postgres/Blob env vars, the app automatically falls back to SQLite/local uploads.
