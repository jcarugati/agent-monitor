"""Minimal secure HTTP serving for the local monitor."""

from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


LOGGER = logging.getLogger(__name__)
SnapshotProvider = Callable[[], dict]
STATIC_MIME_TYPES = {".ico": "image/x-icon"}


class MonitorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _handler_class(static_root: Path, snapshot_provider: SnapshotProvider):
    root = static_root.resolve()

    class MonitorHandler(BaseHTTPRequestHandler):
        server_version = "AgentMonitor/0.1"
        sys_version = ""

        def log_message(self, format_string: str, *args) -> None:
            LOGGER.info("HTTP %s", format_string % args)

        def _common_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )

        def _send_bytes(self, status: int, body: bytes, content_type: str, cache_control: str, *, head_only: bool = False) -> None:
            self.send_response(status)
            self._common_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _send_json(self, status: int, payload: dict, *, head_only: bool = False) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8", "no-store", head_only=head_only)

        def _static_path(self, raw_path: str) -> Path | None:
            decoded = unquote(raw_path)
            if "\x00" in decoded:
                return None
            relative = "index.html" if decoded == "/" else decoded.lstrip("/")
            if any(part == ".." for part in Path(relative).parts):
                return None
            try:
                candidate = (root / relative).resolve(strict=True)
                if not candidate.is_relative_to(root) or not candidate.is_file():
                    return None
                return candidate
            except OSError:
                return None

        def _serve(self, *, head_only: bool = False) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"}, head_only=head_only)
                return
            if parsed.path == "/api/snapshot":
                try:
                    snapshot = snapshot_provider()
                except Exception as exc:  # Boundary: client receives no local details.
                    LOGGER.error("Snapshot generation failed: %s", type(exc).__name__)
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "snapshot unavailable"}, head_only=head_only)
                    return
                self._send_json(HTTPStatus.OK, snapshot, head_only=head_only)
                return
            if parsed.path.startswith("/api/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, head_only=head_only)
                return
            static_path = self._static_path(parsed.path)
            if static_path is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, head_only=head_only)
                return
            try:
                body = static_path.read_bytes()
            except OSError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, head_only=head_only)
                return
            mime_type = STATIC_MIME_TYPES.get(static_path.suffix.lower())
            if mime_type is None:
                mime_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
            if mime_type.startswith("text/") or mime_type in {"application/javascript", "application/json"}:
                mime_type += "; charset=utf-8"
            cache = "no-cache" if static_path.name == "index.html" else "public, max-age=300"
            self._send_bytes(HTTPStatus.OK, body, mime_type, cache, head_only=head_only)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            self._serve()

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
            self._serve(head_only=True)

        def _reject_mutation(self) -> None:
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self._common_headers()
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        do_POST = _reject_mutation
        do_PUT = _reject_mutation
        do_PATCH = _reject_mutation
        do_DELETE = _reject_mutation

    return MonitorHandler


def create_server(host: str, port: int, static_root: str | Path, snapshot_provider: SnapshotProvider) -> MonitorServer:
    return MonitorServer((host, port), _handler_class(Path(static_root), snapshot_provider))
