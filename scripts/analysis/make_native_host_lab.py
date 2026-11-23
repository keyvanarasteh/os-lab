#!/usr/bin/env python3
"""Create owned inert PENT-18 fixtures in a NEW directory; never installs a host."""
import argparse
import json
from pathlib import Path

EXTENSION_ID = "a" * 32


def create_lab(destination: Path) -> Path:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    destination.chmod(0o700)

    def write(path, value):
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    for scenario in ("safe", "risky"):
        root = destination / scenario
        extension = root / "extension"
        extension.mkdir(parents=True)
        root.chmod(0o700)
        write(extension / "manifest.json", {
            "manifest_version": 3, "name": "Owned PENT-18 lab fixture",
            "version": "1.0", "permissions": ["nativeMessaging"],
        })
        (extension / "background.js").write_text(
            "// Inert source for offline analysis; never load in a browser.\n"
            "chrome.runtime.connectNative('org.oslab.echo');\n"
            + ("browser.runtime.sendNativeMessage(computedName, {});\n" if scenario == "risky" else ""),
            encoding="utf-8")
        binary = root / "inert_host.py"
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "# Deliberately not a functional native host; inspect only.\n"
            "raise SystemExit('This fixture must never be executed by the analyzer')\n",
            encoding="utf-8")
        binary.chmod(0o777 if scenario == "risky" else 0o700)
        write(root / "host.json", {
            "name": "org.oslab.echo", "description": "Owned inert offline teaching fixture",
            "type": "stdio", "path": str(binary),
            "allowed_origins": ["*"] if scenario == "risky" else [f"chrome-extension://{EXTENSION_ID}/"],
        })
    print(f"Created owned offline fixtures: {destination}")
    print("No browser registration, network traffic or host execution.")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        create_lab(args.destination)
    except OSError as exc:
        parser.exit(2, f"fixture creation refused: {exc}\n")


if __name__ == "__main__":
    main()
