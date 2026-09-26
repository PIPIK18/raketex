import io
import json
import time
import unittest
from unittest.mock import patch

import app as site
import test_post_segments as post_tests


class LargeUploadTest(unittest.TestCase):
    setUp = post_tests.PostSegmentsTest.setUp
    submit = post_tests.PostSegmentsTest.submit

    def authorize(self, size=6 * 1024 * 1024):
        with patch.object(site, "BLOB_READ_WRITE_TOKEN", "test"):
            response = self.client.post("/admin/uploads/authorize", json={"filename": "launch.mp4", "media_type": "video", "size": size})
        return response

    def test_local_file_exceeding_old_hosted_limit(self):
        response = self.submit([{"id": "v", "type": "video"}], video_v=(io.BytesIO(b"x" * (5 * 1024 * 1024)), "launch.mp4"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(site.list_admin_posts()), 1)
        response.close()
        response.request.close()
        response.request.environ["wsgi.input"].close()

    def test_direct_upload_confirmation_and_save_without_file_payload(self):
        authorized = self.authorize()
        self.assertEqual(authorized.status_code, 200)
        ticket = authorized.json
        reference = "https://test.public.blob.vercel-storage.com/" + ticket["pathname"]
        with patch("vercel.blob.BlobClient") as client:
            client.return_value.head.return_value = {"pathname": ticket["pathname"], "size": 6 * 1024 * 1024, "content_type": "video/mp4", "url": reference}
            confirmed = self.client.post("/admin/uploads/complete", json={"ticket": ticket["ticket"]})
        self.assertEqual(confirmed.status_code, 200)
        segment = {"id": "v", "type": "video", "video_filename": confirmed.json["reference"], "upload_receipt": confirmed.json["receipt"]}
        self.assertEqual(self.submit([segment]).status_code, 200)
        self.assertEqual(site.post_segments(site.list_admin_posts()[0]), [{"type": "video", "video_filename": reference}])
        self.assertEqual(list(site.UPLOAD_DIR.iterdir()), [])

    def test_limit_type_size_and_session_checks(self):
        self.assertEqual(self.authorize(site.MAX_POST_UPLOAD_BYTES).status_code, 200)
        self.assertEqual(self.authorize(site.MAX_POST_UPLOAD_BYTES + 1).status_code, 400)
        self.assertEqual(self.authorize(-1).status_code, 400)
        ticket = self.authorize().json["ticket"]
        self.assertEqual(self.client.post("/admin/uploads/complete", json={"ticket": ticket + "bad"}).status_code, 400)
        with self.client.session_transaction() as session:
            session["upload_owner"] = "different-session"
        self.assertEqual(self.client.post("/admin/uploads/complete", json={"ticket": ticket}).status_code, 400)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.authorize().status_code, 401)

    def test_unverified_reference_and_oversized_total_rejected(self):
        self.assertEqual(self.submit([{"id": "v", "type": "video", "video_filename": "https://example.com/video.mp4"}]).status_code, 400)
        self.authorize()
        with self.client.session_transaction() as session:
            owner = session["upload_owner"]
        segments = []
        for index in range(2):
            reference = f"https://test.public.blob.vercel-storage.com/{index}.mp4"
            receipt = site.sign_upload_ticket({"scope": "uploaded", "owner": owner, "reference": reference,
                                              "media_type": "video", "size": 300 * 1024 * 1024, "exp": time.time() + 60})
            segments.append({"id": str(index), "type": "video", "video_filename": reference, "upload_receipt": receipt})
        response = self.submit(segments)
        self.assertEqual(response.status_code, 400)
        self.assertIn("500 MiB", response.json["error"])
        self.assertEqual(site.list_admin_posts(), [])

    def test_confirm_rejects_wrong_uploaded_size(self):
        ticket = self.authorize().json
        with patch("vercel.blob.BlobClient") as client:
            client.return_value.head.return_value = {"pathname": ticket["pathname"], "size": 1, "content_type": "video/mp4"}
            response = self.client.post("/admin/uploads/complete", json={"ticket": ticket["ticket"]})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
