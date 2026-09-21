import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("RAKETEX_DATA_DIR", BASE_DIR / "instance"))
INSTANCE_DIR = DATA_DIR
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = INSTANCE_DIR / "raketex.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
DB_INIT_DONE = False
PROJECT_STATES = ("ongoing", "finished", "planned")
PRIVATE_BLOB_PREFIX = "blob-private:"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("RAKETEX_SECRET_KEY", "dev-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def using_postgres():
    return bool(DATABASE_URL)


def running_on_vercel():
    return bool(os.environ.get("VERCEL"))


def storage_config_issues():
    issues = []
    if running_on_vercel() and not using_postgres():
        issues.append("Missing DATABASE_URL or POSTGRES_URL. Connect a Vercel Marketplace Postgres database.")
    if running_on_vercel() and not using_blob_storage():
        issues.append("Missing BLOB_READ_WRITE_TOKEN. Connect a Vercel Blob store.")
    return issues


@contextmanager
def get_db():
    if using_postgres():
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            yield conn
        return

    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn


def init_db():
    global DB_INIT_DONE
    if DB_INIT_DONE:
        return

    if not using_blob_storage():
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with get_db() as db:
        if using_postgres():
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'build log',
                    body TEXT NOT NULL,
                    image_filename TEXT,
                    published BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    google_id TEXT UNIQUE NOT NULL,
                    email TEXT,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS comments (
                    id BIGSERIAL PRIMARY KEY,
                    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'build log',
                    body TEXT NOT NULL,
                    image_filename TEXT,
                    published INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_id TEXT UNIQUE NOT NULL,
                    email TEXT,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    user_id INTEGER,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
                )
                """
            )
        ensure_comment_user_id_column(db)
        ensure_post_segments_column(db)
        project_id_type = "BIGSERIAL PRIMARY KEY" if using_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS projects (
                id {project_id_type},
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ongoing', 'finished', 'planned')),
                body TEXT NOT NULL,
                image_filename TEXT,
                segments TEXT NOT NULL,
                published BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    DB_INIT_DONE = True


def ensure_post_segments_column(db):
    if using_postgres():
        db.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS segments TEXT")
    else:
        columns = db.execute("PRAGMA table_info(posts)").fetchall()
        if not any(column["name"] == "segments" for column in columns):
            db.execute("ALTER TABLE posts ADD COLUMN segments TEXT")


def post_segments(post):
    if post is None:
        return []
    if post["segments"] is not None:
        return json.loads(post["segments"])
    # Older posts displayed their image before their body.
    segments = []
    if post["image_filename"]:
        segments.append({"type": "image", "image_filename": post["image_filename"]})
    if post["body"]:
        segments.append({"type": "text", "text": post["body"]})
    return segments


def read_post_segments(post=None):
    try:
        items = json.loads(request.form.get("segments", "[]"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Could not read the segments. Reload the editor and try again.") from exc
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError("Add between 1 and 100 image or text segments.")

    existing_images = {item["image_filename"] for item in post_segments(post) if item["type"] == "image"}
    segments = []
    uploads = []
    seen = set()
    # Validate every segment before uploading any files.
    for position, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError("Invalid content segment.")
        segment_id = item.get("id")
        if not isinstance(segment_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", segment_id) or segment_id in seen:
            raise ValueError("Invalid or duplicate segment ID.")
        seen.add(segment_id)
        if item.get("type") == "text":
            value = item.get("text", "")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Add text to segment {position}, or remove it.")
            segments.append({"type": "text", "text": value.strip()})
        elif item.get("type") == "image":
            upload = request.files.get(f"image_{segment_id}")
            image_ref = item.get("image_filename")
            if upload and upload.filename:
                if not image_is_allowed(upload.filename):
                    raise ValueError(f"Segment {position}: use png, jpg, jpeg, gif or webp images.")
                uploads.append((len(segments), upload))
                image_ref = None
            elif not isinstance(image_ref, str) or image_ref not in existing_images:
                raise ValueError(f"Select an image for segment {position}, or remove it.")
            segments.append({"type": "image", "image_filename": image_ref})
        else:
            raise ValueError("Only image and text segments are supported.")
    for index, upload in uploads:
        segments[index]["image_filename"] = save_uploaded_image(upload)
    return segments


def ensure_comment_user_id_column(db):
    if using_postgres():
        db.execute("ALTER TABLE comments ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL")
        return

    columns = db.execute("PRAGMA table_info(comments)").fetchall()
    if not any(column["name"] == "user_id" for column in columns):
        db.execute("ALTER TABLE comments ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")


def admin_username():
    return os.environ.get("RAKETEX_ADMIN_USER", "admin")


def admin_password_hash():
    password_hash = os.environ.get("RAKETEX_ADMIN_PASSWORD_HASH")
    if password_hash:
        return password_hash
    return generate_password_hash(os.environ.get("RAKETEX_ADMIN_PASSWORD", "raketex123"))


def is_admin():
    return session.get("is_admin") is True


def is_signed_in():
    return is_admin() or bool(session.get("user_id") or session.get("user_name"))


def current_user_name():
    return session.get("user_name") or ("admin" if is_admin() else "")


def current_user_id():
    return session.get("user_id")


def require_admin():
    if not is_admin():
        flash("Sign in first.", "warn")
        return redirect(url_for("login"))
    return None


def google_sign_in_enabled():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def google_redirect_uri():
    return GOOGLE_REDIRECT_URI or url_for("google_callback", _external=True)


def safe_next_url(value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return None
    return value


def request_json(url, data=None, headers=None):
    body = None
    request_headers = headers or {}
    if data is not None:
        body = urlencode(data).encode("utf-8")
        request_headers = {"Content-Type": "application/x-www-form-urlencoded", **request_headers}

    request_obj = UrlRequest(url, data=body, headers=request_headers)
    try:
        with urlopen(request_obj, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google returned {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Google: {exc.reason}") from exc


def image_is_allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def using_blob_storage():
    return bool(BLOB_READ_WRITE_TOKEN)


def is_remote_image(image_ref):
    if not image_ref:
        return False
    parsed = urlparse(image_ref)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_private_blob_ref(image_ref):
    return bool(image_ref and image_ref.startswith(PRIVATE_BLOB_PREFIX))


def private_blob_pathname(image_ref):
    return image_ref.removeprefix(PRIVATE_BLOB_PREFIX)


def post_image_src(image_ref):
    if not image_ref:
        return ""
    if is_private_blob_ref(image_ref):
        return url_for("blob_image", pathname=private_blob_pathname(image_ref))
    if is_remote_image(image_ref):
        return image_ref
    return url_for("uploaded_file", filename=image_ref)


def blob_result_value(blob, key):
    if isinstance(blob, dict):
        return blob.get(key)
    return getattr(blob, key)


def save_uploaded_image(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not image_is_allowed(file_storage.filename):
        raise ValueError("Use png, jpg, jpeg, gif or webp images.")

    original_name = secure_filename(file_storage.filename)
    suffix = Path(original_name).suffix.lower()
    filename = f"{uuid.uuid4().hex}{suffix}"

    if using_blob_storage():
        from vercel.blob import BlobClient

        pathname = f"uploads/{filename}"
        content = file_storage.read()
        content_type = file_storage.mimetype or None
        client = BlobClient()

        try:
            blob = client.put(
                pathname,
                content,
                access="public",
                content_type=content_type,
                add_random_suffix=False,
            )
            return blob_result_value(blob, "url")
        except Exception as exc:
            if "private store" not in str(exc).lower():
                raise

            blob = client.put(
                pathname,
                content,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
            )
            return f"{PRIVATE_BLOB_PREFIX}{blob_result_value(blob, 'pathname')}"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_storage.save(UPLOAD_DIR / filename)
    return filename


def search_public_posts(search_query):
    with get_db() as db:
        if search_query:
            like_query = f"%{search_query.lower()}%"
            if using_postgres():
                return db.execute(
                    """
                    SELECT * FROM posts
                    WHERE published = TRUE
                      AND (
                        LOWER(title) LIKE %s
                        OR LOWER(body) LIKE %s
                        OR LOWER(category) LIKE %s
                      )
                    ORDER BY created_at DESC
                    """,
                    (like_query, like_query, like_query),
                ).fetchall()

            return db.execute(
                """
                SELECT * FROM posts
                WHERE published = 1
                  AND (
                    LOWER(title) LIKE ?
                    OR LOWER(body) LIKE ?
                    OR LOWER(category) LIKE ?
                  )
                ORDER BY created_at DESC
                """,
                (like_query, like_query, like_query),
            ).fetchall()

        if using_postgres():
            return db.execute(
                """
                SELECT * FROM posts
                WHERE published = TRUE
                ORDER BY created_at DESC
                """
            ).fetchall()

        return db.execute(
            """
            SELECT * FROM posts
            WHERE published = 1
            ORDER BY created_at DESC
            """
        ).fetchall()


def get_post(post_id, include_drafts=False):
    with get_db() as db:
        if using_postgres():
            return db.execute(
                """
                SELECT * FROM posts
                WHERE id = %s AND (published = TRUE OR %s = TRUE)
                """,
                (post_id, include_drafts),
            ).fetchone()

        return db.execute(
            """
            SELECT * FROM posts
            WHERE id = ? AND (published = 1 OR ? = 1)
            """,
            (post_id, 1 if include_drafts else 0),
        ).fetchone()


def list_comments(post_id):
    with get_db() as db:
        if using_postgres():
            return db.execute(
                """
                SELECT
                    comments.*,
                    COALESCE(users.display_name, comments.author) AS display_author,
                    users.avatar_url AS avatar_url
                FROM comments
                LEFT JOIN users ON users.id = comments.user_id
                WHERE comments.post_id = %s
                ORDER BY comments.created_at ASC, comments.id ASC
                """,
                (post_id,),
            ).fetchall()

        return db.execute(
            """
            SELECT
                comments.*,
                COALESCE(users.display_name, comments.author) AS display_author,
                users.avatar_url AS avatar_url
            FROM comments
            LEFT JOIN users ON users.id = comments.user_id
            WHERE comments.post_id = ?
            ORDER BY comments.created_at ASC, comments.id ASC
            """,
            (post_id,),
        ).fetchall()


def create_comment(post_id, user_id, author, body):
    with get_db() as db:
        if using_postgres():
            db.execute(
                """
                INSERT INTO comments (post_id, user_id, author, body, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (post_id, user_id, author, body, now_iso()),
            )
            return

        db.execute(
            """
            INSERT INTO comments (post_id, user_id, author, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (post_id, user_id, author, body, now_iso()),
        )


def upsert_google_user(google_id, email, display_name, avatar_url):
    timestamp = now_iso()
    with get_db() as db:
        if using_postgres():
            user = db.execute("SELECT * FROM users WHERE google_id = %s", (google_id,)).fetchone()
            if user:
                db.execute(
                    """
                    UPDATE users
                    SET email = %s, display_name = %s, avatar_url = %s
                    WHERE id = %s
                    """,
                    (email, display_name, avatar_url, user["id"]),
                )
                return db.execute("SELECT * FROM users WHERE id = %s", (user["id"],)).fetchone()

            return db.execute(
                """
                INSERT INTO users (google_id, email, display_name, avatar_url, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (google_id, email, display_name, avatar_url, timestamp),
            ).fetchone()

        user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
        if user:
            db.execute(
                """
                UPDATE users
                SET email = ?, display_name = ?, avatar_url = ?
                WHERE id = ?
                """,
                (email, display_name, avatar_url, user["id"]),
            )
            return db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()

        cursor = db.execute(
            """
            INSERT INTO users (google_id, email, display_name, avatar_url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (google_id, email, display_name, avatar_url, timestamp),
        )
        return db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()


def get_comment(comment_id):
    with get_db() as db:
        if using_postgres():
            return db.execute("SELECT * FROM comments WHERE id = %s", (comment_id,)).fetchone()
        return db.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()


def delete_comment_by_id(comment_id):
    with get_db() as db:
        if using_postgres():
            db.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
            return
        db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))


def list_admin_posts():
    with get_db() as db:
        return db.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()


def list_projects(status=None, include_drafts=False):
    marker = "%s" if using_postgres() else "?"
    conditions = [f"(published = TRUE OR {marker} = TRUE)"]
    values = [include_drafts]
    if status is not None:
        conditions.append(f"status = {marker}")
        values.append(status)
    with get_db() as db:
        return db.execute(
            f"SELECT * FROM projects WHERE {' AND '.join(conditions)} ORDER BY created_at DESC, id DESC",
            tuple(values),
        ).fetchall()


def get_project(project_id, include_drafts=False):
    marker = "%s" if using_postgres() else "?"
    with get_db() as db:
        return db.execute(
            f"SELECT * FROM projects WHERE id = {marker} AND (published = TRUE OR {marker} = TRUE)",
            (project_id, include_drafts),
        ).fetchone()


def save_project(project_id, title, category, status, body, image_filename, published, segments):
    marker = "%s" if using_postgres() else "?"
    values = (title, category, status, body, image_filename, published, json.dumps(segments), now_iso())
    with get_db() as db:
        if project_id is None:
            db.execute(
                "INSERT INTO projects (title, category, status, body, image_filename, published, segments, updated_at, created_at) "
                f"VALUES ({', '.join([marker] * 9)})", values + (values[-1],),
            )
        else:
            columns = ("title", "category", "status", "body", "image_filename", "published", "segments", "updated_at")
            assignments = ", ".join(f"{column} = {marker}" for column in columns)
            db.execute(f"UPDATE projects SET {assignments} WHERE id = {marker}", values + (project_id,))


def posts_for_project(project):
    marker = "%s" if using_postgres() else "?"
    with get_db() as db:
        return db.execute(
            f"SELECT * FROM posts WHERE published = TRUE AND LOWER(TRIM(category)) = LOWER({marker}) ORDER BY created_at DESC, id DESC",
            (project["category"].strip(),),
        ).fetchall()


def create_post(title, category, body, image_filename, published, segments=None):
    timestamp = now_iso()
    segments_json = json.dumps(segments) if segments is not None else None
    with get_db() as db:
        if using_postgres():
            db.execute(
                """
                INSERT INTO posts (title, category, body, image_filename, published, created_at, updated_at, segments)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (title, category, body, image_filename, published, timestamp, timestamp, segments_json),
            )
            return

        db.execute(
            """
            INSERT INTO posts (title, category, body, image_filename, published, created_at, updated_at, segments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, category, body, image_filename, 1 if published else 0, timestamp, timestamp, segments_json),
        )


def update_post(post_id, title, category, body, image_filename, published, segments=None):
    segments_json = json.dumps(segments) if segments is not None else None
    with get_db() as db:
        if using_postgres():
            db.execute(
                """
                UPDATE posts
                SET title = %s, category = %s, body = %s, image_filename = %s, published = %s, updated_at = %s, segments = %s
                WHERE id = %s
                """,
                (title, category, body, image_filename, published, now_iso(), segments_json, post_id),
            )
            return

        db.execute(
            """
            UPDATE posts
            SET title = ?, category = ?, body = ?, image_filename = ?, published = ?, updated_at = ?, segments = ?
            WHERE id = ?
            """,
            (title, category, body, image_filename, 1 if published else 0, now_iso(), segments_json, post_id),
        )


def delete_post_by_id(post_id):
    with get_db() as db:
        if using_postgres():
            db.execute("DELETE FROM posts WHERE id = %s", (post_id,))
            return
        db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))


def storage_check():
    try:
        init_db()
        with get_db() as db:
            if using_postgres():
                db.execute("SELECT 1").fetchone()
            else:
                db.execute("SELECT 1").fetchone()
        return None
    except Exception as exc:
        app.logger.exception("Storage check failed")
        return str(exc)


@app.before_request
def ensure_database():
    if request.endpoint in {"healthz", "asset_file", "workspace_asset_file"}:
        return None

    issues = storage_config_issues()
    if issues:
        return render_template("setup_error.html", issues=issues), 503

    try:
        init_db()
    except Exception as exc:
        app.logger.exception("Storage initialization failed")
        return render_template("setup_error.html", issues=["Storage initialization failed."], detail=str(exc)), 500
    return None


@app.context_processor
def inject_admin_state():
    return {
        "is_admin": is_admin(),
        "is_signed_in": is_signed_in(),
        "current_user_name": current_user_name(),
        "google_sign_in_enabled": google_sign_in_enabled(),
        "post_image_src": post_image_src,
        "post_segments": post_segments,
        "project_states": PROJECT_STATES,
    }


@app.route("/healthz")
def healthz():
    issues = storage_config_issues()
    storage_error = None if issues else storage_check()
    return jsonify(
        {
            "ok": not issues and storage_error is None,
            "running_on_vercel": running_on_vercel(),
            "using_postgres": using_postgres(),
            "using_blob_storage": using_blob_storage(),
            "database_env": "DATABASE_URL" if os.environ.get("DATABASE_URL") else "POSTGRES_URL" if os.environ.get("POSTGRES_URL") else None,
            "issues": issues,
            "storage_error": storage_error,
        }
    )


@app.route("/")
def home():
    search_query = request.args.get("q", "").strip()
    posts = search_public_posts(search_query)
    return render_template("home.html", posts=posts, search_query=search_query)


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    post = get_post(post_id, include_drafts=is_admin())
    if post is None:
        return render_template("404.html"), 404
    comments = list_comments(post_id)
    return render_template("post.html", post=post, comments=comments)


@app.route("/projects")
def projects():
    status = request.args.get("status", "ongoing")
    if status not in PROJECT_STATES:
        return render_template("404.html"), 404
    return render_template("projects.html", projects=list_projects(status), selected_status=status)


@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    project = get_project(project_id, include_drafts=is_admin())
    if project is None:
        return render_template("404.html"), 404
    return render_template("project.html", project=project, selected_status=project["status"])


@app.route("/projects/<int:project_id>/posts")
def project_posts(project_id):
    project = get_project(project_id, include_drafts=is_admin())
    if project is None:
        return render_template("404.html"), 404
    return render_template("home.html", posts=posts_for_project(project), project=project, selected_status=project["status"])


@app.route("/post/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    post = get_post(post_id, include_drafts=is_admin())
    if post is None:
        return render_template("404.html"), 404
    if not is_signed_in():
        flash("Sign in with user first.", "warn")
        comment_target = f"{url_for('post_detail', post_id=post_id)}#comments"
        return redirect(url_for("login", next=comment_target))

    author = current_user_name()
    body = request.form.get("body", "").strip()

    if not body:
        flash("Write a comment first.", "warn")
        return redirect(url_for("post_detail", post_id=post_id) + "#comments")
    if len(body) > 1200:
        flash("Comment is too long. Keep it under 1200 characters.", "warn")
        return redirect(url_for("post_detail", post_id=post_id) + "#comments")

    try:
        create_comment(post_id, current_user_id(), author, body)
    except Exception as exc:
        app.logger.exception("Comment creation failed")
        flash(f"Comment failed: {exc}", "warn")
        return redirect(url_for("post_detail", post_id=post_id) + "#comments")

    flash("Comment posted.", "ok")
    return redirect(url_for("post_detail", post_id=post_id) + "#comments")


@app.route("/comments/<int:comment_id>/delete", methods=["POST"])
def delete_comment(comment_id):
    blocked = require_admin()
    if blocked:
        return blocked

    comment = get_comment(comment_id)
    if comment is None:
        flash("Comment not found.", "warn")
        return redirect(url_for("home"))

    post_id = comment["post_id"]
    delete_comment_by_id(comment_id)
    flash("Comment deleted.", "ok")
    return redirect(url_for("post_detail", post_id=post_id) + "#comments")


@app.route("/admin")
def admin():
    blocked = require_admin()
    if blocked:
        return blocked
    posts = list_admin_posts()
    return render_template("admin.html", posts=posts)


@app.route("/admin/projects")
def admin_projects():
    blocked = require_admin()
    if blocked:
        return blocked
    return render_template("admin_projects.html", projects=list_projects(include_drafts=True))


@app.route("/admin/login", methods=["GET", "POST"])
@app.route("/user/login", methods=["GET", "POST"])
def login():
    auth_mode = request.args.get("mode", "signin")
    if auth_mode not in {"signin", "login"}:
        auth_mode = "signin"

    if request.method == "POST":
        auth_mode = "login"
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == admin_username() and check_password_hash(admin_password_hash(), password):
            session.clear()
            session["is_admin"] = True
            session["user_name"] = admin_username()
            flash("Signed in.", "ok")
            return redirect(safe_next_url(request.args.get("next")) or url_for("admin"))
        flash("Wrong username or password.", "warn")
    return render_template("login.html", auth_mode=auth_mode)


@app.route("/login/google")
def google_login():
    if not google_sign_in_enabled():
        flash("Google sign-in is not configured yet.", "warn")
        return redirect(url_for("login"))

    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    session["oauth_next"] = safe_next_url(request.args.get("next"))
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@app.route("/auth/google/callback")
def google_callback():
    if not google_sign_in_enabled():
        flash("Google sign-in is not configured yet.", "warn")
        return redirect(url_for("login"))

    error = request.args.get("error")
    if error:
        flash(f"Google sign-in failed: {error}", "warn")
        return redirect(url_for("login"))

    state = request.args.get("state")
    if not state or state != session.pop("google_oauth_state", None):
        flash("Google sign-in state did not match. Try again.", "warn")
        return redirect(url_for("login"))

    code = request.args.get("code")
    if not code:
        flash("Google sign-in did not return a code.", "warn")
        return redirect(url_for("login"))

    try:
        token = request_json(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        access_token = token.get("access_token")
        if not access_token:
            raise RuntimeError("Google did not return an access token.")
        userinfo = request_json(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except RuntimeError as exc:
        app.logger.exception("Google sign-in failed")
        flash(str(exc), "warn")
        return redirect(url_for("login"))

    google_id = userinfo.get("sub")
    display_name = (userinfo.get("name") or userinfo.get("email") or "user").strip()

    if not google_id:
        flash("Google sign-in did not return a user id.", "warn")
        return redirect(url_for("login"))

    user = upsert_google_user(
        google_id=google_id,
        email=userinfo.get("email"),
        display_name=display_name[:80],
        avatar_url=userinfo.get("picture"),
    )
    next_url = session.pop("oauth_next", None)
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["display_name"]
    session["is_admin"] = False
    flash("Signed in.", "ok")
    return redirect(next_url or url_for("home"))


@app.route("/admin/logout", methods=["POST"])
@app.route("/user/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("home"))


def post_editor(post=None, is_project=False):
    content_type = "project" if is_project else "post"
    admin_endpoint = "admin_projects" if is_project else "admin"
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip() or (title if is_project else "build log")
        published = request.form.get("published") == "on"
        try:
            if not title:
                raise ValueError("Add a title before saving.")
            status = request.form.get("status", "ongoing")
            if is_project and status not in PROJECT_STATES:
                raise ValueError("Choose ongoing, finished, or planned for the project state.")
            segments = read_post_segments(post)
            body = "\n\n".join(item["text"] for item in segments if item["type"] == "text")
            image_filename = next((item["image_filename"] for item in segments if item["type"] == "image"), None)
            if is_project:
                save_project(post["id"] if post else None, title, category, status, body, image_filename, published, segments)
            elif post is None:
                create_post(title, category, body, image_filename, published, segments)
            else:
                update_post(post["id"], title, category, body, image_filename, published, segments)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("%s save failed", content_type.capitalize())
            return jsonify(error=f"Could not save your {content_type}. Your segments are still here; please try again."), 500
        flash(f"{content_type.capitalize()} {'created' if post is None else 'updated'}.", "ok")
        return jsonify(redirect=url_for(admin_endpoint))
    editor_segments = [
        {**item, "image_src": post_image_src(item["image_filename"])} if item["type"] == "image" else item
        for item in post_segments(post)
    ]
    return render_template("post_form.html", post=post, editor_segments=editor_segments,
                           is_project=is_project, content_type=content_type, admin_endpoint=admin_endpoint)


@app.route("/admin/projects/new", methods=["GET", "POST"])
def new_project():
    blocked = require_admin()
    if blocked:
        return blocked
    return post_editor(is_project=True)


@app.route("/admin/projects/<int:project_id>/edit", methods=["GET", "POST"])
def edit_project(project_id):
    blocked = require_admin()
    if blocked:
        return blocked
    project = get_project(project_id, include_drafts=True)
    if project is None:
        return render_template("404.html"), 404
    return post_editor(project, is_project=True)


@app.route("/admin/projects/<int:project_id>/delete", methods=["POST"])
def delete_project(project_id):
    blocked = require_admin()
    if blocked:
        return blocked
    if get_project(project_id, include_drafts=True) is None:
        return render_template("404.html"), 404
    marker = "%s" if using_postgres() else "?"
    try:
        with get_db() as db:
            db.execute(f"DELETE FROM projects WHERE id = {marker}", (project_id,))
    except Exception:
        app.logger.exception("Project deletion failed")
        flash("Could not delete the project. Please try again.", "warn")
    else:
        flash("Project deleted. Its posts are still available.", "ok")
    return redirect(url_for("admin_projects"))


@app.route("/admin/posts/new", methods=["GET", "POST"])
def new_post():
    blocked = require_admin()
    if blocked:
        return blocked
    return post_editor()


@app.route("/admin/posts/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    blocked = require_admin()
    if blocked:
        return blocked
    post = get_post(post_id, include_drafts=True)
    if post is None:
        return render_template("404.html"), 404
    return post_editor(post)


@app.route("/admin/posts/<int:post_id>/delete", methods=["POST"])
def delete_post(post_id):
    blocked = require_admin()
    if blocked:
        return blocked
    try:
        delete_post_by_id(post_id)
    except Exception as exc:
        app.logger.exception("Post deletion failed")
        flash(f"Post deletion failed: {exc}", "warn")
        return redirect(url_for("admin"))
    flash("Post deleted.", "ok")
    return redirect(url_for("admin"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/blob/<path:pathname>")
def blob_image(pathname):
    from vercel.blob import BlobClient

    blob = BlobClient().get(pathname, access="private")
    content = blob_result_value(blob, "content")
    content_type = blob_result_value(blob, "content_type") or "application/octet-stream"
    return Response(content, mimetype=content_type)


@app.route("/assets/<path:filename>")
def asset_file(filename):
    return send_from_directory(BASE_DIR / "assets", filename)


@app.route("/workspace-assets/<path:filename>")
def workspace_asset_file(filename):
    return send_from_directory(BASE_DIR.parent, filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
