"""``python3 -m source_lab.electron <app_dir | app.asar>`` entry point (PENT-10)."""

from __future__ import annotations

from .inject_map import main

if __name__ == "__main__":
    raise SystemExit(main())
