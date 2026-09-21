import io
import json
import unittest
from unittest.mock import patch

import app as site
import test_post_segments as post_tests


class ProjectsTest(unittest.TestCase):
    setUp = post_tests.PostSegmentsTest.setUp

    def submit(self, path="/admin/projects/new", **extra):
        data = {
            "title": "Falcon", "category": "", "status": "ongoing", "published": "on",
            "segments": json.dumps([{"id": "a", "type": "text", "text": "Project introduction"}]),
        }
        data.update(extra)
        return self.client.post(path, data=data, content_type="multipart/form-data")

    def test_create_filter_and_change_state(self):
        for state in site.PROJECT_STATES:
            response = self.submit(title=f"Rocket {state}", status=state)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["redirect"], "/admin/projects")
        for state in site.PROJECT_STATES:
            projects = site.list_projects(state)
            self.assertEqual(len(projects), 1)
            page = self.client.get(f"/projects?status={state}").text
            self.assertIn(f"Rocket {state}", page)
            for other in set(site.PROJECT_STATES) - {state}:
                self.assertNotIn(f"Rocket {other}", page)
        project = site.list_projects("ongoing")[0]
        self.assertEqual(project["category"], "Rocket ongoing")
        self.assertEqual(self.submit(f'/admin/projects/{project["id"]}/edit', status="finished").status_code, 200)
        self.assertEqual(len(site.list_projects("ongoing")), 0)
        self.assertEqual(len(site.list_projects("finished")), 2)
        self.assertEqual(self.client.get("/projects?status=invalid").status_code, 404)

    def test_segments_reopen_reorder_and_render(self):
        items = [{"id": "a", "type": "text", "text": "Start"}, {"id": "b", "type": "image"},
                 {"id": "c", "type": "text", "text": "End"}, {"id": "d", "type": "image"}]
        response = self.submit(segments=json.dumps(items), image_b=(io.BytesIO(b"one"), "one.png"),
                               image_d=(io.BytesIO(b"two"), "two.jpg"))
        self.assertEqual(response.status_code, 200)
        project = site.list_projects()[0]
        original = site.post_segments(project)
        reordered = [dict(segment, id=str(i)) for i, segment in enumerate(reversed(original))]
        path = f'/admin/projects/{project["id"]}/edit'
        self.assertIn("Edit Project", self.client.get(path).text)
        self.assertEqual(self.submit(path, segments=json.dumps(reordered)).status_code, 200)
        updated = site.get_project(project["id"])
        self.assertEqual(site.post_segments(updated), list(reversed(original)))
        page = self.client.get(f'/projects/{project["id"]}').text
        self.assertLess(page.index(original[3]["image_filename"]), page.index('>End</div>'))
        self.assertLess(page.index('>End</div>'), page.index(original[1]["image_filename"]))
        self.assertIn("view project posts", page)
        self.assertEqual(updated["body"], "End\n\nStart")
        self.assertEqual(updated["image_filename"], original[3]["image_filename"])

    def test_related_posts_match_category_only_and_exclude_drafts(self):
        self.submit(category="Falcon")
        project = site.list_projects()[0]
        for title, category, published in [
            ("Matching", "falcon", True), ("Spaces", " Falcon ", True),
            ("Similar", "Falcon Heavy", True), ("Falcon in title", "other", True), ("Secret", "Falcon", False),
        ]:
            site.create_post(title, category, "body", None, published)
        self.assertEqual({post["title"] for post in site.posts_for_project(project)}, {"Matching", "Spaces"})
        page = self.client.get(f'/projects/{project["id"]}/posts').text
        for title in ["Matching", "Spaces"]:
            self.assertIn(f"<h2>{title}</h2>", page)
        for title in ["Similar", "Falcon in title", "Secret"]:
            self.assertNotIn(f"<h2>{title}</h2>", page)
        # Category matching treats SQL wildcard characters literally.
        self.submit(category="%_'")
        exact = next(p for p in site.list_projects() if p["category"] == "%_'")
        self.assertEqual(site.posts_for_project(exact), [])

    def test_draft_privacy_and_admin_authorization(self):
        self.submit(published="")
        project = site.list_projects(include_drafts=True)[0]
        self.assertEqual(site.list_projects(), [])
        detail = f'/projects/{project["id"]}'
        self.assertEqual(self.client.get(detail).status_code, 200)
        with self.client.session_transaction() as session:
            session.clear()
            session["user_name"] = "Regular user"
        for path in [detail, detail + "/posts"]:
            self.assertEqual(self.client.get(path).status_code, 404)
        for path in ["/admin/projects", "/admin/projects/new", f'/admin/projects/{project["id"]}/edit']:
            self.assertEqual(self.client.get(path).status_code, 302)
        for path in ["/admin/projects/new", f'/admin/projects/{project["id"]}/edit', f'/admin/projects/{project["id"]}/delete']:
            self.assertEqual(self.submit(path).status_code, 302)
        self.assertEqual(len(site.list_projects(include_drafts=True)), 1)

    def test_delete_keeps_posts_and_missing_projects_return_404(self):
        self.submit()
        project = site.list_projects()[0]
        site.create_post("Related", "Falcon", "Keep this", None, True)
        response = self.client.post(f'/admin/projects/{project["id"]}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(site.list_projects(), [])
        self.assertEqual(len(site.list_admin_posts()), 1)
        for path in [f'/projects/{project["id"]}', f'/projects/{project["id"]}/posts', f'/admin/projects/{project["id"]}/edit']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_invalid_and_failed_save_preserve_existing_project(self):
        for extra in [{"status": "unknown"}, {"title": " "}, {"segments": "[]"}]:
            self.assertEqual(self.submit(**extra).status_code, 400)
        self.assertEqual(site.list_projects(), [])
        self.submit()
        project = site.list_projects()[0]
        path = f'/admin/projects/{project["id"]}/edit'
        with patch.object(site, "save_project", side_effect=RuntimeError("offline")), self.assertLogs(site.app.logger, level="ERROR"):
            self.assertEqual(self.submit(path, title="Changed").status_code, 500)
        self.assertEqual(site.get_project(project["id"])["title"], "Falcon")
        site.DB_INIT_DONE = False
        site.init_db()
        self.assertEqual(len(site.list_projects()), 1)


if __name__ == "__main__":
    unittest.main()
