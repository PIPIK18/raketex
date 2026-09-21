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
                    assert not errors, errors
                    browser.close()
                    print("PASS: desktop drag, mobile touch drag, keyboard reorder, previews, failed-save recovery, persistence, removal, and public rendering")
            finally:
                server.shutdown()
                thread.join()
                server.server_close()


if __name__ == "__main__":
    main()
