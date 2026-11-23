"""Web Lab HTTP contracts (``/api/web/...``).

Web Lab is the embedded in-app browser lab: a Rust engine (``web-lab/browser``,
crate ``weblab``) hosts real webview windows with JavaScript injection, and this
module is the console's bridge to it. The console never re-implements the
engine: it reports readiness, starts/stops the local engine process, and
proxies the engine's own JSON API on 127.0.0.1. Like the Cleanup Lab module,
everything is stdlib-only and typed: unknown routes and unvalidated bodies fail
explicitly.

Readiness states (the dashboard renders what the backend decides):

- ``ready``       — the engine answers ``/healthz``
- ``stopped``     — the engine binary is built but not running
- ``needs-setup`` — the binary is missing; ``./labctl web setup`` builds it
- ``unavailable`` — the binary is missing and cargo is not installed

The engine binds to 127.0.0.1 only and keeps every capture in memory; the
proxy adds no storage of its own (``web-lab/knowledge/sessions.md``).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request

#: Default port of the engine's loopback control API (web-lab/.env.example).
DEFAULT_PORT = 5077
#: Proxied prefixes — everything else under /api/web is refused.
GET_ROUTES = ("/api/web/overview", "/api/web/windows", "/api/web/injections",
              "/api/web/events", "/api/web/profiles", "/api/web/status")
POST_ROUTES = ("/api/web/windows", "/api/web/windows/", "/api/web/injections",
               "/api/web/profiles", "/api/web/engine/start", "/api/web/engine/stop")
DELETE_ROUTES = ("/api/web/windows/", "/api/web/injections/")
#: Paths the console answers itself, never proxied.
LOCAL_POST = ("/api/web/engine/start", "/api/web/engine/stop")
MAX_BODY = 512 * 1024


class WebLabError(ValueError):
    """A request the Web Lab refused, with the HTTP status to answer."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def engine_port() -> int:
    raw = os.environ.get("WEBLAB_ENGINE_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError as exc:
        raise WebLabError(500, f"WEBLAB_ENGINE_PORT is not a number: {raw}") from exc
    if not 0 < port < 65536:
        raise WebLabError(500, f"WEBLAB_ENGINE_PORT out of range: {port}")
    return port


def binary_path(root) -> str:
    suffix = ".exe" if platform.system() == "Windows" else ""
    binary_name = f"weblab{suffix}"
    env_path = os.environ.get("WEBLAB_BINARY")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    candidates = [
        os.path.join(root, "web-lab", "browser", "target", "release", binary_name),
        os.path.join(root, "web-lab", "bin", binary_name),
        os.path.join(root, "web-lab", binary_name),
    ]
    tools_dir = os.path.normpath(os.path.join(root, "..", "tools"))
    if os.path.isdir(tools_dir):
        candidates.append(os.path.join(tools_dir, binary_name))
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return candidates[0]


def _healthz(port: int, timeout=1.0):
    """The engine's /healthz body when it is running, else ``None``."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


class WebLabAPI:
    """Console-side Web Lab endpoints (``/api/web/...``)."""

    def __init__(self, root, port=None):
        self.root = root
        self.port = port if port is not None else engine_port()
        self.lab_dir = os.path.join(root, "web-lab")
        self.process = None
        self.log_path = os.path.join(self.lab_dir, "storage", "engine.log")
        self.pid_path = os.path.join(self.lab_dir, "storage", "engine.pid")

    # ── readiness ────────────────────────────────────────────────────────────

    def state(self) -> str:
        """ready | stopped | needs-setup | unavailable — the backend decides."""
        if _healthz(self.port) is not None:
            return "ready"
        if os.path.isfile(binary_path(self.root)) and os.access(binary_path(self.root), os.X_OK):
            return "stopped"
        import shutil
        if shutil.which("cargo") is None:
            return "unavailable"
        return "needs-setup"

    def status(self) -> dict:
        health = _healthz(self.port)
        built = os.path.isfile(binary_path(self.root)) and os.access(binary_path(self.root), os.X_OK)
        return {
            "state": "ready" if health else ("stopped" if built else self.state()),
            "port": self.port,
            "binary": built,
            "engine": health,
        }

    # ── engine lifecycle ─────────────────────────────────────────────────────

    def start_engine(self) -> dict:
        health = _healthz(self.port)
        if health is not None:
            return {"state": "ready", "alreadyRunning": True, "engine": health}
        binary = binary_path(self.root)
        if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
            raise WebLabError(
                409,
                "The Web Lab engine is not built — run ./labctl web setup",
            )
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log = open(self.log_path, "ab")
        try:
            self.process = subprocess.Popen(
                [binary, "serve", "--port", str(self.port)],
                cwd=self.lab_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        finally:
            log.close()
        with open(self.pid_path, "w", encoding="utf-8") as handle:
            handle.write(str(self.process.pid))
        deadline = time.time() + 10
        while time.time() < deadline:
            health = _healthz(self.port)
            if health is not None:
                return {"state": "ready", "pid": self.process.pid, "engine": health}
            if self.process.poll() is not None:
                raise WebLabError(
                    502,
                    f"The engine exited with code {self.process.returncode} — see web-lab/storage/engine.log",
                )
            time.sleep(0.25)
        raise WebLabError(504, "The engine did not answer /healthz within 10 s")

    def stop_engine(self) -> dict:
        result = {"stopped": False}
        try:
            self._proxy("POST", "/api/web/engine/stop", b"{}")
            result["stopped"] = True
        except WebLabError:
            pass
        pid = self._read_pid()
        if pid:
            try:
                os.kill(pid, 15)
                result["stopped"] = True
            except OSError:
                pass
            try:
                os.remove(self.pid_path)
            except OSError:
                pass
        return result

    def _read_pid(self):
        try:
            with open(self.pid_path, encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            return None

    # ── proxy ────────────────────────────────────────────────────────────────

    def _proxy(self, method: str, path: str, body: bytes = b"") -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body if method in ("POST", "DELETE") else None,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as reply:
                return json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                message = json.loads(detail).get("error", detail)
            except ValueError:
                message = detail or f"engine answered {exc.code}"
            raise WebLabError(exc.code, str(message)) from exc
        except (urllib.error.URLError, OSError):
            raise WebLabError(
                503,
                "The Web Lab engine is not running — start it from the Web Lab page",
            ) from None

    # ── routing ──────────────────────────────────────────────────────────────

    def get(self, path: str, query: dict) -> dict:
        if path == "/api/web/status":
            return self.status()
        if path not in GET_ROUTES:
            raise WebLabError(404, f"Unknown Web Lab route: {path}")
        forward = path
        if query:
            from urllib.parse import urlencode
            forward = f"{forward}?{urlencode({key: values[0] for key, values in query.items()})}"
        return self._proxy("GET", forward)

    def post(self, path: str, data: dict) -> dict:
        if not path.startswith(POST_ROUTES):
            raise WebLabError(404, f"Unknown Web Lab route: {path}")
        if path in LOCAL_POST:
            if path == "/api/web/engine/start":
                return self.start_engine()
            return self.stop_engine()
        body = json.dumps(data, allow_nan=False).encode("utf-8")
        if len(body) > MAX_BODY:
            raise WebLabError(413, "Request body too large")
        if path == "/api/web/windows" and "url" not in data:
            raise WebLabError(400, "Opening a window needs a url")
        return self._proxy("POST", path, body)

    def delete(self, path: str) -> dict:
        if not path.startswith(DELETE_ROUTES):
            raise WebLabError(404, f"Unknown Web Lab route: {path}")
        return self._proxy("DELETE", path)
