"""Optional browser regression: pip install playwright, then python tests/browser_post_editor.py.

Uses installed Chrome and an isolated temporary database; never touches real posts.
"""
import base64
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

import app as site


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4z8AAAAASUVORK5CYII=")


def check_projects(page, origin):
    page.set_viewport_size({"width": 1280, "height": 1600})
    page.locator(".menu").get_by_role("link", name="admin", exact=True).click()
    page.get_by_role("link", name="manage projects", exact=True).click()
    page.get_by_role("link", name="new project", exact=True).click()
    page.get_by_label("project name", exact=True).fill("Falcon test project")
    page.get_by_label("post category", exact=True).fill("build log")
    page.get_by_label("project state", exact=True).select_option("ongoing")
    for text in ["Meet our new rocket project.", "Follow the build in the project posts."]:
        page.locator("[data-add='text']").click()
        page.locator("textarea").last.fill(text)
    page.locator("[data-add='image']").click()
    page.locator("input[type='file']").set_input_files({"name": "project.png", "mimeType": "image/png", "buffer": PNG})
    page.locator(".segment-handle").last.focus()
    page.keyboard.press("ArrowUp")
    page.locator("#save-post").click()
    page.wait_for_url(origin + "/admin/projects")
    project = site.list_projects()[0]
    assert project["category"] == "build log"
    assert [s["type"] for s in site.post_segments(project)] == ["text", "image", "text"]

    # Public navigation, familiar post row layout, and project introduction.
    page.locator(".menu").get_by_role("link", name="projects", exact=True).click()
    assert page.locator(".project-tabs a").all_text_contents() == ["ongoing", "finished", "planned"]
    assert page.locator(".blog-entry h2").all_text_contents() == ["Falcon test project"]
    page.locator(".blog-entry").click()
    assert page.locator(".post-segments > *").evaluate_all("items => items.map(i => i.tagName)") == ["DIV", "IMG", "DIV"]
    site.create_post("Unrelated post", "somewhere else", "Nothing to do with this project", None, True)
    page.get_by_role("link", name="view project posts", exact=True).click()
    assert page.locator(".blog-entry h2").all_text_contents() == ["Browser segment test"]
    page.get_by_role("link", name="back to project", exact=True).click()
    page.get_by_role("link", name="edit project", exact=True).click()
    assert page.locator(".segment").count() == 3
    assert page.locator(".image-preview.visible").count() == 1
    page.get_by_label("project state", exact=True).select_option("finished")
    page.locator("#save-post").click()
    page.wait_for_url(origin + "/admin/projects")
    page.locator(".menu").get_by_role("link", name="projects", exact=True).click()
    assert page.locator(".blog-entry").count() == 0
    page.locator(".project-tabs").get_by_role("link", name="finished", exact=True).click()
    assert page.locator(".blog-entry h2").all_text_contents() == ["Falcon test project"]
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "raketex-projects-desktop.png"), full_page=True)
    for width in [800, 390, 320]:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (width, page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.tagName, e.className, e.getBoundingClientRect().width])"))
        assert page.locator(".menu").get_by_role("link", name="projects", exact=True).is_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "raketex-projects-mobile.png"), full_page=True)
    page.locator(".project-tabs").get_by_role("link", name="planned", exact=True).click()
    assert page.locator(".blog-entry").count() == 0
    page.get_by_role("link", name="manage projects", exact=True).click()
    page.locator(".admin-card").get_by_role("button", name="delete", exact=True).click()
    page.wait_for_url(origin + "/admin/projects")
    assert site.list_projects() == []
    assert len(site.list_admin_posts()) == 2
    page.context.clear_cookies()
    page.goto(origin + "/projects")
    assert page.locator(".menu").get_by_role("link", name="projects", exact=True).is_visible()
    assert page.locator(".menu").get_by_role("link", name="admin", exact=True).count() == 0
    print("PASS: project creation, reusable editor, state changes, category-linked posts, deletion, visitor navigation, and responsive layouts")


def check_video_contact_navigation(page, origin):
    cookie = site.app.session_interface.get_signing_serializer(site.app).dumps({"is_admin": True})
    page.context.add_cookies([{"name": "session", "value": cookie, "url": origin}])
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.goto(origin + "/admin/posts/new")
    # One-second VP8 fixture generated with ffmpeg; no network or encoder needed at test time.
    clip = (Path(__file__).parent / "fixtures" / "clip.webm").read_bytes()
    page.locator("#title").fill("Video launch test")
    page.locator("[data-add='video']").click()
    page.locator("input[type='file']").set_input_files({"name": "launch.webm", "mimeType": "video/webm", "buffer": bytes(clip)})
    page.wait_for_function("document.querySelector('video').readyState >= 1 || document.querySelector('video').error")
    assert page.locator("video").evaluate("video => !video.error"), (len(clip), page.locator("video").evaluate("video => ({src: video.src, error: video.error?.message})"))
    page.locator("[data-add='text']").click()
    page.locator("textarea").fill("Video description")
    page.locator(".segment-handle").last.focus()
    page.keyboard.press("ArrowUp")
    page.locator("#save-post").click()
    page.wait_for_url(origin + "/admin")
    post = next(p for p in site.list_admin_posts() if p["title"] == "Video launch test")
    page.goto(origin + f'/post/{post["id"]}')
    page.wait_for_function("document.querySelector('video').readyState >= 1")
    page.locator("video").evaluate("video => video.play()")
    page.wait_for_function("document.querySelector('video').currentTime > 0")
    page.locator("video").evaluate("video => video.pause()")
    page.goto(origin + f'/admin/posts/{post["id"]}/edit')
    page.wait_for_function("document.querySelector('video').readyState >= 1")
    assert page.locator(".segment").count() == 2

    page.locator(".menu").get_by_role("link", name="contact", exact=True).click()
    page.get_by_role("link", name="edit contact", exact=True).click()
    page.locator("#intro").fill("Get in touch with RAKETEX.")
    for label, url in [("Website", "https://example.com/raketex"), ("Email", "mailto:hello@example.com")]:
        page.get_by_role("button", name="+ add link", exact=True).click()
        page.locator("input[name='link_label']").last.fill(label)
        page.locator("input[name='link_url']").last.fill(url)
    page.get_by_role("button", name="save contact", exact=True).click()
    page.wait_for_url(origin + "/contact")
    assert page.locator(".contact-link").count() == 2
    assert page.locator(".contact-link").last.get_attribute("href") == "mailto:hello@example.com"
    logo = page.locator(".logo").bounding_box()
    left = page.locator(".nav-left").bounding_box()
    right = page.locator(".nav-right").bounding_box()
    assert left["x"] + left["width"] <= logo["x"] < right["x"]
    assert page.locator(".nav-link").first.evaluate("e => getComputedStyle(e).clipPath") == "none"
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "raketex-contact-desktop.png"), full_page=True)
    page.emulate_media(reduced_motion="reduce")
    assert page.locator(".nav-link").first.evaluate("e => getComputedStyle(e).transitionDuration") == "0s"
    page.emulate_media(reduced_motion="no-preference")
    for width in [800, 390, 320]:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
        assert page.locator(".menu").get_by_role("link", name="contact", exact=True).is_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "raketex-contact-mobile.png"), full_page=True)
    page.get_by_role("link", name="edit contact", exact=True).click()
    page.get_by_role("button", name="remove link", exact=True).first.click()
    page.get_by_role("button", name="save contact", exact=True).click()
    page.wait_for_url(origin + "/contact")
    assert page.locator(".contact-link").count() == 1
    print("PASS: real video upload, playback and reopen; Contact editing; centered text navigation, mobile layout, reduced motion")


def check_large_direct_upload(page, origin):
    size = 6 * 1024 * 1024
    uploads = []
    saves = []
    module = """
      export async function upload(path, file, options) {
        options.onUploadProgress({percentage: 50});
        const response = await fetch('/test-blob-upload', {method: 'PUT', body: file});
        if (!response.ok) throw new Error('Upload failed');
        return {pathname: path};
      }
    """
    page.route("**/assets/blob-client.js", lambda route: route.fulfill(content_type="text/javascript", body=module))

    def blob_upload(route):
        uploads.append(len(route.request.post_data_buffer))
        route.fulfill(status=200, body="ok")

    def save_post(route):
        saves.append(len(route.request.post_data_buffer))
        if len(saves) == 1:
            route.fulfill(status=500, content_type="application/json", body='{"error":"Temporary save failure"}')
        else:
            route.continue_()

    page.route("**/test-blob-upload", blob_upload)
    page.goto(origin + "/admin/posts/new")
    page.locator("#post-editor").evaluate("form => form.dataset.directUploads = 'true'")
    page.locator("#title").fill("Large direct upload")
    page.locator("[data-add='video']").click()
    page.locator("input[type='file']").set_input_files({"name": "large.mp4", "mimeType": "video/mp4", "buffer": b"x" * size})
    page.route("**/admin/posts/new", save_post)
    with patch.object(site, "BLOB_READ_WRITE_TOKEN", "test"), patch("vercel.blob.BlobClient") as client:
        client.return_value.head.side_effect = lambda path: {"pathname": path, "size": size, "content_type": "video/mp4", "url": "https://test.public.blob.vercel-storage.com/" + path}
        page.locator("#save-post").click()
        page.locator("#editor-error").wait_for(state="visible")
        assert "Temporary save failure" in page.locator("#editor-error").inner_text()
        assert page.locator("input[type='file']").evaluate("input => input.files[0].size") == size
        page.locator("#save-post").click()
        page.wait_for_url(origin + "/admin")
    assert uploads == [size], uploads
    assert len(saves) == 2 and all(length < 10000 for length in saves), saves
    assert any(post["title"] == "Large direct upload" for post in site.list_admin_posts())
    page.unroute("**/assets/blob-client.js")
    page.unroute("**/test-blob-upload")
    page.unroute("**/admin/posts/new")
    print("PASS: 6 MiB direct upload with mocked storage, small Flask save requests, and retry without reupload")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.multiple(site, INSTANCE_DIR=root, UPLOAD_DIR=root / "uploads", DB_PATH=root / "posts.db",
                            DATABASE_URL=None, BLOB_READ_WRITE_TOKEN=None, DB_INIT_DONE=False), \
                patch.object(site, "running_on_vercel", return_value=False):
            site.init_db()
            server = make_server("127.0.0.1", 0, site.app, request_handler=QuietHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f"http://127.0.0.1:{server.server_port}"
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    context = browser.new_context(viewport={"width": 1280, "height": 2000}, has_touch=True)
                    cookie = site.app.session_interface.get_signing_serializer(site.app).dumps({"is_admin": True})
                    context.add_cookies([{"name": "session", "value": cookie, "url": origin}])
                    page = context.new_page()
                    page.set_default_timeout(10000)
                    page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(origin + "/admin/posts/new")
                    page.get_by_role("button", name="Reject analytics").click()
                    page.locator("#title").fill("Browser segment test")
                    page.locator("#category").fill("build log")
                    page.locator("[data-add='text']").click()
                    page.locator("textarea").last.fill("Opening text")
                    page.locator("[data-add='image']").click()
                    page.locator("input[type='file']").last.set_input_files({"name": "first.png", "mimeType": "image/png", "buffer": PNG})
                    page.locator("[data-add='text']").click()
                    page.locator("textarea").last.fill("Closing text")
                    page.locator("[data-add='image']").click()
                    page.locator("input[type='file']").last.set_input_files({"name": "second.png", "mimeType": "image/png", "buffer": PNG})
                    page.wait_for_function("Array.from(document.querySelectorAll('.image-preview')).every(i => i.complete && i.naturalWidth > 0)")
                    assert page.locator(".image-preview.visible").count() == 2

                    # Real mouse drag: move the first text segment to the end.
                    handle = page.locator(".segment-handle").first.bounding_box()
                    last = page.locator(".segment").last.bounding_box()
                    page.mouse.move(handle["x"] + 15, handle["y"] + 15)
                    page.mouse.down()
                    page.mouse.move(last["x"] + 100, last["y"] + last["height"] - 10, steps=20)
                    page.mouse.up()
                    assert page.locator(".segment").last.locator("textarea").input_value() == "Opening text"
                    assert page.locator("input[type='file']").first.evaluate("e => e.files[0].name") == "first.png"

                    # A failed save must retain text, file selections, and ordering.
                    page.route("**/admin/posts/new", lambda route: route.fulfill(status=413, body="Too large"))
                    page.locator("#save-post").click()
                    page.locator("#editor-error").wait_for(state="visible")
                    assert "too large" in page.locator("#editor-error").inner_text()
                    assert page.locator(".segment").count() == 4
                    assert page.locator("input[type='file']").first.evaluate("e => e.files[0].name") == "first.png"
                    page.unroute("**/admin/posts/new")
                    page.locator("#save-post").click()
                    page.wait_for_url(origin + "/admin")
                    post = site.list_admin_posts()[0]
                    assert [s["type"] for s in site.post_segments(post)] == ["image", "text", "image", "text"]

                    # Reopen, check previews and keyboard movement, then remove a segment.
                    page.goto(origin + f'/admin/posts/{post["id"]}/edit')
                    assert page.locator(".image-preview.visible").count() == 2
                    page.locator(".segment-handle").last.focus()
                    page.keyboard.press("ArrowUp")
                    assert page.locator(".segment").nth(2).locator("textarea").input_value() == "Opening text"
                    page.locator("[data-action='remove']").last.click()
                    assert page.locator(".segment").count() == 3

                    # Mobile layout and actual touch drag via Chrome's input protocol.
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator(".segment-handle").nth(1).scroll_into_view_if_needed()
                    handle = page.locator(".segment-handle").nth(1).bounding_box()
                    target = page.locator(".segment").last.bounding_box()
                    cdp = context.new_cdp_session(page)
                    x = handle["x"] + 15
                    start_y = handle["y"] + 15
                    end_y = min(780, target["y"] + target["height"] - 10)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": start_y}]})
                    for step in range(1, 11):
                        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": start_y + (end_y - start_y) * step / 10}]})
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    assert page.locator(".segment").last.locator("textarea").input_value() == "Closing text"
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.locator("#save-post").click()
                    page.wait_for_url(origin + "/admin")
                    page.goto(origin + f'/post/{post["id"]}')
                    assert page.locator(".post-segments > *").evaluate_all("items => items.map(i => i.tagName)") == ["IMG", "DIV", "DIV"]
                    assert page.locator(".post-body").all_text_contents() == ["Opening text", "Closing text"]
                    check_projects(page, origin)
                    check_video_contact_navigation(page, origin)
                    check_large_direct_upload(page, origin)
                    assert not errors, errors
                    browser.close()
                    print("PASS: desktop drag, mobile touch drag, keyboard reorder, previews, failed-save recovery, persistence, removal, and public rendering")
            finally:
                server.shutdown()
                thread.join()
                server.server_close()


if __name__ == "__main__":
    main()
