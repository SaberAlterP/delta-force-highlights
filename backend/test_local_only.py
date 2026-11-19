"""本机访问限制：挡住其他网页的跨站写请求和 DNS 重绑定。"""
import asyncio
import json
from unittest import TestCase

from app.main import app


def call(method, path, headers=None, body=b""):
    """不依赖 httpx，直接按 ASGI 调用应用（不触发启动事件）。"""
    headers = {"host": "127.0.0.1:8000", **(headers or {})}
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


class LocalOnlyTests(TestCase):
    def test_health_from_local_page(self):
        self.assertEqual(call("GET", "/api/health"), 200)
        self.assertEqual(call("GET", "/api/health", {"host": "localhost:8000"}), 200)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(call("GET", "/api/health", {"host": "evil.example:8000"}), 403)

    def test_cross_site_post_is_rejected(self):
        status = call("POST", "/api/workflow/abc/delete-bundle", {"origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_same_origin_and_vite_posts_pass_the_guard(self):
        body = json.dumps({"min_operators": "x"}).encode()
        for origin in ("http://127.0.0.1:8000", "http://127.0.0.1:5173"):
            status = call("POST", "/api/workflow/settings",
                          {"origin": origin, "content-type": "application/json"}, body)
            self.assertNotEqual(status, 403, origin)
