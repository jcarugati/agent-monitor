import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from agent_monitor.http import create_server


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static_root = Path(self.temp.name)
        (self.static_root / "index.html").write_text("<!doctype html><title>Monitor</title>", encoding="utf-8")
        (self.static_root / "app.js").write_text("console.log('monitor');", encoding="utf-8")
        self.snapshot = {"generated_at": "2026-08-29T12:00:00Z", "running_count": 0, "running_threads": [], "recent_count": 0, "recent_completions": []}
        self.server = create_server("127.0.0.1", 0, self.static_root, lambda: self.snapshot)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def test_health_is_json_no_store_and_has_security_headers(self):
        status, headers, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_snapshot_returns_provider_data_without_cache(self):
        status, headers, body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), self.snapshot)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_static_files_serve_with_safe_cache_policy(self):
        index_status, index_headers, index_body = self.request("GET", "/")
        asset_status, asset_headers, asset_body = self.request("GET", "/app.js")
        self.assertEqual((index_status, asset_status), (200, 200))
        self.assertIn(b"Monitor", index_body)
        self.assertIn(b"console.log", asset_body)
        self.assertEqual(index_headers["Cache-Control"], "no-cache")
        self.assertEqual(asset_headers["Cache-Control"], "public, max-age=300")

    def test_traversal_missing_routes_and_mutations_are_rejected(self):
        self.assertEqual(self.request("GET", "/%2e%2e/AGENTS.md")[0], 404)
        self.assertEqual(self.request("GET", "/api/unknown")[0], 404)
        self.assertEqual(self.request("POST", "/api/snapshot")[0], 405)

    def test_snapshot_errors_do_not_leak_internals(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        def broken():
            raise RuntimeError("secret /private/database path")

        self.server = create_server("127.0.0.1", 0, self.static_root, broken)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        with self.assertLogs("agent_monitor.http", level="ERROR"):
            status, _, body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "snapshot unavailable"})
        self.assertNotIn(b"private", body)
        self.assertNotIn(b"secret", body)


if __name__ == "__main__":
    unittest.main()
