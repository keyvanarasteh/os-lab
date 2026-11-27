#!/usr/bin/env python3
"""mitmproxy addon — log intercepted HTTP(S) flows from the lab app.

Load it into mitmproxy once SSL pinning is disabled and the device proxy points
at mitmproxy:

    mitmdump -s lab/scripts/mitm_addon.py --set flow_log=runs/flows.log

Each request/response pair is written as a single line (method, status, url and
content-length) to the log file, and a running JSON summary of unique hosts is
printed on exit. The line formatter is a pure function so it is unit-tested with
no mitmproxy and no traffic.

Only lab traffic should reach this proxy; the pipeline's scope guard and the
emulator-only proxy host keep it that way.
"""
from __future__ import annotations

import argparse
import json


def format_flow_line(method: str, status: int | str, url: str, length: int = 0) -> str:
    """Return one audit line for a completed request/response flow."""
    method = (method or "?").upper()
    return f"{method:<7} {status!s:>3}  {length:>8}B  {url}"


def host_of(url: str) -> str:
    """Return the host portion of a URL (cheap, no urllib dependency at import)."""
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].split("?", 1)[0]


class FlowLogger:
    """mitmproxy addon class (duck-typed; mitmproxy calls these hooks)."""

    def __init__(self, log_path: str = "flows.log") -> None:
        self.log_path = log_path
        self.hosts: dict[str, int] = {}
        self._fh = None

    # --- mitmproxy option plumbing (optional) ---
    def load(self, loader) -> None:  # pragma: no cover - needs mitmproxy
        loader.add_option(
            "flow_log", str, self.log_path, "Path to write the flow audit log"
        )

    def configure(self, updated) -> None:  # pragma: no cover - needs mitmproxy
        import mitmproxy.ctx as ctx

        if "flow_log" in updated:
            self.log_path = ctx.options.flow_log

    # --- the actual interception hook ---
    def response(self, flow) -> None:  # pragma: no cover - needs mitmproxy
        url = flow.request.pretty_url
        length = len(flow.response.content or b"")
        line = format_flow_line(
            flow.request.method, flow.response.status_code, url, length
        )
        self._record(line, host_of(url))

    def done(self) -> None:  # pragma: no cover - needs mitmproxy
        if self._fh:
            self._fh.close()
        print(json.dumps({"hosts": self.hosts}, indent=2))

    def _record(self, line: str, host: str) -> None:  # pragma: no cover
        if self._fh is None:
            self._fh = open(self.log_path, "a", encoding="utf-8")
        self._fh.write(line + "\n")
        self._fh.flush()
        self.hosts[host] = self.hosts.get(host, 0) + 1


# mitmproxy looks for a module-level ``addons`` list.
addons = [FlowLogger()]


def main(argv: list[str] | None = None) -> int:
    # Standalone demo of the pure formatter (no mitmproxy needed).
    parser = argparse.ArgumentParser(description="Preview a flow log line.")
    parser.add_argument("method")
    parser.add_argument("status")
    parser.add_argument("url")
    parser.add_argument("--length", type=int, default=0)
    args = parser.parse_args(argv)
    print(format_flow_line(args.method, args.status, args.url, args.length))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
