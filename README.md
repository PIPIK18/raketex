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

## Post editor

In **New Post**, enter a title and category, then use **add image**, **add video**,
or **add text** to build the post. Images and videos have their own uploads and
previews. Videos support MP4, WebM, and OGV, with playback controls on the public
page. Use browser-compatible encoding (such as H.264 in MP4). Drag the handle at
the left of a segment to reorder it (mouse or touch), or use the up/down buttons.
Focused drag handles also support the keyboard arrow keys. **Remove** removes
that segment from the post. Save publishes the segments in their displayed order;
uncheck **published** to save a draft.

Existing posts open as an image segment followed by a text segment. The app adds
the `posts.segments` column automatically on startup for SQLite and Postgres;
existing content is retained. The first image becomes the list thumbnail, and
all text segments contribute to search and excerpts. Posts may contain only
images, videos, or text, with up to 100 segments. New files can total **500 MiB
per save**, locally and on Vercel. On Vercel the browser uploads media directly
to Blob storage using its [client upload flow](https://vercel.com/docs/vercel-blob/client-upload),
so file contents do not pass through the function's small request limit.
Only the post text and verified file references go to Flask. Upload progress is
shown in the editor; retrying a failed save reuses completed uploads.
The editor checks the combined size before submitting. Existing saved media is reused
when reordering or editing a post, so it does not need to be uploaded again.
Failed saves keep the editor content and file selections available for retry.

Large uploads use the existing `BLOB_READ_WRITE_TOKEN` and `RAKETEX_SECRET_KEY`
environment variables. Both must be configured on Vercel. `vercel.json` routes
`/api/blob-upload` to the small Node function which issues restricted upload
tokens after verifying Flask's signed administrator authorization. Deploy the
updated configuration, `api/` files, package manifests, and browser assets together.
Public stores serve files directly; private files stream through Flask with
byte-range support, without buffering the whole video in memory. Blob storage
and transfer usage still count toward the connected storage plan.

The browser SDK bundle is checked in at `assets/blob-client.js`; rebuild it after
changing the pinned JavaScript dependency using `npm ci` and `npm run build:uploads`.
Run the upload authorization tests with `npm run test:uploads`.

Run the isolated backend regression tests with:

```powershell
python -m unittest discover -s tests -v
```

Optional browser checks require Playwright and an installed Chrome browser:

```powershell
python -m pip install playwright
python tests/browser_post_editor.py
```

Both suites use temporary databases and uploads, leaving real posts untouched.

## Projects

The **projects** navigation item opens the **ongoing**, **finished**, and
**planned** tabs below the logo. Projects use the same list layout as posts;
clicking one opens its introduction with ordered text and image segments.

Use **admin → manage projects → new project** to create one. Enter a name,
choose its state, and build the introduction with the existing segment editor.
Projects can be edited, moved between states, saved as drafts, or deleted.
Drafts are visible only to administrators. Deleting a project keeps its posts.

The **post category** field links a project to posts. Leaving it blank uses the
project name; enter an existing category to connect existing posts instead.
**View project posts** shows published posts with that exact category, ignoring
capitalization and surrounding spaces. For example, `Falcon` matches `falcon`
but not `Falcon Heavy`. Renaming a project does not rename its existing category
or any posts; edit the post category separately if needed.

The `projects` table is created automatically for SQLite and Postgres when the
app starts. The browser checks also exercise project creation, state changes,
category links, deletion, and responsive layouts.

## Contact and navigation

**Contact** is available in the main navigation. Use **Admin → Edit contact**
to add an optional introduction and up to 30 labeled links, or edit/remove links.
Use a display name such as `YouTube` or `Email`, then enter the destination in
the address field. Plain email addresses automatically become clickable email
links. Full `https://`, `http://`, `mailto:`, and `tel:` addresses also work.
Changes are saved to the database and appear on the public Contact page.

The header places uppercase text navigation on either side of the centered
RAKETEX logo, with animated underlines and hover movement. On smaller screens,
links wrap below the logo. Reduced-motion preferences disable the animation.

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
