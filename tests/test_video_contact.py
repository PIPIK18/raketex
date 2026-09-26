import io
import json
import unittest
from unittest.mock import patch, MagicMock

from werkzeug.datastructures import MultiDict

import app as site
import test_post_segments as post_tests


class VideoAndContactTest(unittest.TestCase):
    setUp = post_tests.PostSegmentsTest.setUp
    submit = post_tests.PostSegmentsTest.submit

    def test_video_upload_reorder_replace_remove_and_byte_ranges(self):
        segments = [{"id": "v", "type": "video"}, {"id": "t", "type": "text", "text": "Launch"}]
        response = self.submit(segments, video_v=(io.BytesIO(b"0123456789"), "launch.webm"))
        self.assertEqual(response.status_code, 200)
        post = site.list_admin_posts()[0]
        saved = site.post_segments(post)
        self.assertIsNone(post["image_filename"])
        filename = saved[0]["video_filename"]
        page = self.client.get(f'/post/{post["id"]}').text
        self.assertIn('<video class="post-video" controls playsinline', page)
        self.assertIn(filename, page)
        media = self.client.get(f"/uploads/{filename}", headers={"Range": "bytes=2-5"})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(media.data, b"2345")
        media.close()
        path = f'/admin/posts/{post["id"]}/edit'
        reordered = [dict(saved[1], id="t"), dict(saved[0], id="v")]
        self.assertEqual(self.submit(reordered, path).status_code, 200)
        self.assertEqual(site.post_segments(site.get_post(post["id"]))[1], saved[0])
        self.assertEqual(self.submit(reordered, path, video_v=(io.BytesIO(b"replacement"), "next.mp4")).status_code, 200)
        self.assertNotEqual(site.post_segments(site.get_post(post["id"]))[1]["video_filename"], filename)
        self.assertEqual(self.submit([reordered[0]], path).status_code, 200)
        self.assertEqual(len(site.post_segments(site.get_post(post["id"]))), 1)

    def test_invalid_or_foreign_video_is_rejected(self):
        for filename in ["bad.exe", "bad.svg", "bad.mov"]:
            self.assertEqual(self.submit([{"id": "v", "type": "video"}], video_v=(io.BytesIO(b"bad"), filename)).status_code, 400)
        self.assertEqual(self.submit([{"id": "v", "type": "video", "video_filename": "unknown.mp4"}]).status_code, 400)
        self.assertEqual(site.list_admin_posts(), [])
        self.assertEqual(list(site.UPLOAD_DIR.iterdir()), [])

    def test_blob_video_content_type_and_private_range_response(self):
        with patch.object(site, "BLOB_READ_WRITE_TOKEN", "test"), patch("vercel.blob.BlobClient") as blob:
            blob.return_value.put.return_value = {"url": "https://media.example/launch.mp4"}
            self.assertEqual(self.submit([{"id": "v", "type": "video"}], video_v=(io.BytesIO(b"video"), "launch.mp4")).status_code, 200)
            self.assertEqual(blob.return_value.put.call_args.kwargs["content_type"], "video/mp4")
            blob.return_value.head.return_value = {"size": 10, "content_type": "video/mp4", "url": "https://test.private.blob.vercel-storage.com/uploads/launch.mp4"}
            stream = MagicMock(status=206)
            stream.read.side_effect = [b"3456", b""]
            with patch.object(site, "urlopen", return_value=stream) as opened:
                result = self.client.get("/blob/uploads/launch.mp4", headers={"Range": "bytes=3-6"})
                self.assertEqual(result.status_code, 206)
                self.assertEqual(result.data, b"3456")
                self.assertEqual(opened.call_args.args[0].get_header("Range"), "bytes=3-6")
                stream.close.assert_called()

    def test_contact_save_edit_remove_and_public_view(self):
        data = MultiDict([("intro", "Get in touch"), ("link_label", "Website"), ("link_url", "https://example.com"),
                          ("link_label", "Email"), ("link_url", "mailto:hello@example.com")])
        self.assertEqual(self.client.post("/admin/contact", data=data).status_code, 302)
        self.assertEqual(len(site.contact_content()["links"]), 2)
        with self.client.session_transaction() as session:
            session.clear()
        page = self.client.get("/contact").text
        self.assertIn('href="mailto:hello@example.com"', page)
        self.assertIn('rel="noopener noreferrer"', page)
        self.assertNotIn("edit contact", page)
        self.assertEqual(self.client.post("/admin/contact", data={"intro": "hijack"}).status_code, 302)
        self.assertEqual(site.contact_content()["intro"], "Get in touch")
        with self.client.session_transaction() as session:
            session["is_admin"] = True
        self.assertEqual(self.client.post("/admin/contact", data={"intro": "New text"}).status_code, 302)
        self.assertEqual(site.contact_content(), {"intro": "New text", "links": []})

    def test_contact_rejects_unsafe_links_and_retains_form(self):
        for url in ["javascript:alert(1)", "data:text/html,test", "//example.com", "https://", "mailto:", "https://[invalid"]:
            response = self.client.post("/admin/contact", data={"intro": "Keep this", "link_label": "Label", "link_url": url})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Keep this", response.text)
            self.assertEqual(site.contact_content()["links"], [])
        self.assertTrue(site.validate_contact_link("tel:+420123456789"))
        self.assertTrue(site.validate_contact_link("https://example.com/contact?q=hello"))

    def test_contact_accepts_plain_email_alongside_youtube(self):
        data = MultiDict([
            ("link_label", "https://www.youtube.com/"),
            ("link_url", "https://www.youtube.com/@example-channel"),
            ("link_label", "https://mail.google.com/"),
            ("link_url", "  creator+contact@example.com  "),
        ])
        response = self.client.post("/admin/contact", data=data)
        self.assertEqual(response.status_code, 302)
        links = site.contact_content()["links"]
        self.assertEqual(links[0]["url"], "https://www.youtube.com/@example-channel")
        self.assertEqual(links[1]["url"], "mailto:creator+contact@example.com")
        self.assertIn('href="mailto:creator+contact@example.com"', self.client.get("/contact").text)
        self.assertEqual(site.normalize_contact_link(links[1]["url"]), links[1]["url"])

    def test_contact_error_identifies_invalid_row(self):
        response = self.client.post("/admin/contact", data=MultiDict([
            ("link_label", "YouTube"), ("link_url", "https://youtube.com/@example"),
            ("link_label", "Email"), ("link_url", "not-an-address"),
        ]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Link 2:", response.text)
        self.assertIn("https://youtube.com/@example", response.text)
        self.assertIn("not-an-address", response.text)
        self.assertEqual(site.contact_content()["links"], [])


if __name__ == "__main__":
    unittest.main()
