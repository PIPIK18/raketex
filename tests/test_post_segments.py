import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as site


class PostSegmentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = patch.multiple(
            site, INSTANCE_DIR=root, UPLOAD_DIR=root / "uploads", DB_PATH=root / "posts.db",
            DATABASE_URL=None, BLOB_READ_WRITE_TOKEN=None, DB_INIT_DONE=False,
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        self.vercel = patch.object(site, "running_on_vercel", return_value=False)
        self.vercel.start()
        self.addCleanup(self.vercel.stop)
        self.client = site.app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
        site.init_db()

    def submit(self, segments, path="/admin/posts/new", **extra):
        data = {"title": "Rocket build", "category": "testing", "published": "on", "segments": json.dumps(segments)}
        data.update(extra)
        return self.client.post(path, data=data, content_type="multipart/form-data")

    def test_create_render_search_and_edit_order(self):
        response = self.submit([
            {"id": "a", "type": "text", "text": "First paragraph"},
            {"id": "b", "type": "image"},
            {"id": "c", "type": "text", "text": "Second searchable paragraph"},
            {"id": "d", "type": "image"},
        ], image_b=(io.BytesIO(b"first image"), "one.png"), image_d=(io.BytesIO(b"second image"), "two.webp"))
        self.assertEqual(response.status_code, 200)
        post = site.list_admin_posts()[0]
        segments = site.post_segments(post)
        self.assertEqual([s["type"] for s in segments], ["text", "image", "text", "image"])
        self.assertEqual(post["image_filename"], segments[1]["image_filename"])
        self.assertIn("Second searchable paragraph", post["body"])
        self.assertEqual(len(site.search_public_posts("searchable")), 1)
        page = self.client.get(f'/post/{post["id"]}').text
        self.assertLess(page.index("First paragraph"), page.index(segments[1]["image_filename"]))
        self.assertLess(page.index(segments[1]["image_filename"]), page.index("Second searchable paragraph"))
        self.assertLess(page.index("Second searchable paragraph"), page.index(segments[3]["image_filename"]))
        reordered = [dict(segments[i], id=str(i)) for i in [3, 2, 1, 0]]
        response = self.submit(reordered, f'/admin/posts/{post["id"]}/edit')
        self.assertEqual(response.status_code, 200)
        updated = site.get_post(post["id"])
        self.assertEqual(updated["image_filename"], segments[3]["image_filename"])
        self.assertEqual(site.post_segments(updated), [segments[i] for i in [3, 2, 1, 0]])
        self.assertEqual(len(list(site.UPLOAD_DIR.iterdir())), 2)

    def test_replace_and_remove_images_and_image_only_post(self):
        self.assertEqual(self.submit([{"id": "a", "type": "image"}], image_a=(io.BytesIO(b"one"), "one.png")).status_code, 200)
        post = site.list_admin_posts()[0]
        path = f'/admin/posts/{post["id"]}/edit'
        self.assertEqual(post["body"], "")
        response = self.submit([{"id": "b", "type": "image", "image_filename": post["image_filename"]}], path,
                               image_b=(io.BytesIO(b"replacement"), "replacement.jpg"))
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(site.get_post(post["id"])["image_filename"], post["image_filename"])
        self.assertEqual(self.submit([{"id": "c", "type": "text", "text": "Only text now"}], path).status_code, 200)
        self.assertIsNone(site.get_post(post["id"])["image_filename"])

    def test_legacy_post_migration_is_repeatable_and_editable(self):
        # Recreate the posts table as it existed before segment support.
        with closing(sqlite3.connect(site.DB_PATH)) as db:
            db.execute("DROP TABLE posts")
            db.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, category TEXT, body TEXT, image_filename TEXT, published INTEGER, created_at TEXT, updated_at TEXT)")
            db.execute("INSERT INTO posts VALUES (1, 'Legacy', 'build log', 'Old body', 'old.png', 1, '2026-01-01', '2026-01-01')")
            db.commit()
        for _ in range(2):
            site.DB_INIT_DONE = False
            site.init_db()
        legacy = site.get_post(1)
        self.assertIsNone(legacy["segments"])
        segments = site.post_segments(legacy)
        self.assertEqual([s["type"] for s in segments], ["image", "text"])
        self.assertIn("Old body", self.client.get("/admin/posts/1/edit").text)
        self.assertEqual(self.submit([dict(s, id=str(i)) for i, s in enumerate(segments)], "/admin/posts/1/edit").status_code, 200)
        self.assertEqual(site.post_segments(site.get_post(1)), segments)

    def test_invalid_input_does_not_save_or_upload(self):
        cases = [[], {}, [{"id": "a", "type": "unknown"}], [{"id": "a", "type": "text", "text": "   "}],
                 [{"id": "a", "type": "image", "image_filename": "https://untrusted.example/pic.jpg"}],
                 [{"id": "a", "type": "text", "text": "one"}, {"id": "a", "type": "text", "text": "two"}],
                 [{"id": "../bad", "type": "text", "text": "one"}]]
        for segments in cases:
            with self.subTest(segments=segments):
                self.assertEqual(self.submit(segments).status_code, 400)
        self.assertEqual(self.client.post("/admin/posts/new", data={"title": "Invalid", "segments": "not json"}).status_code, 400)
        self.assertEqual(self.submit([{"id": "a", "type": "image"}, {"id": "b", "type": "image"}],
                                    image_a=(io.BytesIO(b"one"), "one.png"), image_b=(io.BytesIO(b"bad"), "bad.svg")).status_code, 400)
        self.assertEqual(site.list_admin_posts(), [])
        self.assertEqual(list(site.UPLOAD_DIR.iterdir()), [])

    def test_draft_auth_and_escaped_text(self):
        content = '<script>alert("test")</script>'
        self.assertEqual(self.submit([{"id": "a", "type": "text", "text": content}], published="").status_code, 200)
        post = site.list_admin_posts()[0]
        page = self.client.get(f'/post/{post["id"]}').text
        self.assertNotIn(content, page)
        self.assertIn("&lt;script&gt;", page)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get(f'/post/{post["id"]}').status_code, 404)
        self.assertEqual(self.submit([{"id": "a", "type": "text", "text": "blocked"}]).status_code, 302)
        self.assertEqual(len(site.list_admin_posts()), 1)

    def test_failed_upload_does_not_overwrite_post(self):
        site.create_post("Keep", "test", "Original", None, True)
        post = site.list_admin_posts()[0]
        with patch.object(site, "save_uploaded_image", side_effect=RuntimeError("offline")), self.assertLogs(site.app.logger, level="ERROR"):
            response = self.submit([{"id": "a", "type": "image"}], f'/admin/posts/{post["id"]}/edit',
                                   image_a=(io.BytesIO(b"image"), "photo.png"))
        self.assertEqual(response.status_code, 500)
        self.assertIn("still here", response.json["error"])
        self.assertEqual(site.get_post(post["id"])["body"], "Original")


if __name__ == "__main__":
    unittest.main()
