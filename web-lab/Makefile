# Web Lab Makefile — engine-style lab (no VM): targets delegate to cargo and
# the built `weblab` engine. `./labctl web <target>` lands here.
PORT ?= 5077
CARGO ?= cargo
BROWSER_DIR := browser
ENGINE := $(BROWSER_DIR)/target/release/weblab

.PHONY: help preflight doctor setup up start stop status monitor open events test clean

help:
	@echo "Web Lab: embedded in-app browser with JavaScript injection"
	@echo "  make preflight | doctor   check cargo and the platform webview runtime"
	@echo "  make setup                build the engine (cargo build --release)"
	@echo "  make up                   start the engine on PORT=$(PORT)"
	@echo "  make stop                 stop a running engine"
	@echo "  make status               report engine readiness"
	@echo "  make open URL=https://example.com [PORT=$(PORT)]  open a lab window"
	@echo "  make test                 run engine unit tests"
	@echo "  make clean                remove build artifacts"

preflight doctor:
	@command -v $(CARGO) >/dev/null 2>&1 || { echo "cargo not found — install Rust via rustup"; exit 1; }
	@$(CARGO) --version
	@case "$$(uname -s)" in \
	  Darwin) echo "webview runtime: WKWebView (system framework)" ;; \
	  Linux)  pkg-config --exists gtk+-3.0 webkit2gtk-4.1 2>/dev/null && echo "webview runtime: WebKitGTK ok" \
	          || { echo "WebKitGTK development packages missing (libwebkit2gtk-4.1-dev, libgtk-3-dev)"; exit 1; } ;; \
	  MINGW*|MSYS*|Windows_NT) echo "webview runtime: WebView2 (bundled with Windows 10/11)" ;; \
	esac

setup: $(ENGINE)

$(ENGINE):
	cd $(BROWSER_DIR) && $(CARGO) build --release

up: $(ENGINE)
	@curl -fsS "http://127.0.0.1:$(PORT)/healthz" >/dev/null 2>&1 && { echo "engine already running on $(PORT)"; exit 0; }
	@mkdir -p storage
	@WEBLAB_ENGINE_PORT=$(PORT) nohup $(ENGINE) serve --port $(PORT) >> storage/engine.log 2>&1 & echo $$! > storage/engine.pid
	@for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS "http://127.0.0.1:$(PORT)/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
	@curl -fsS "http://127.0.0.1:$(PORT)/healthz" && echo && echo "engine running (pid $$(cat storage/engine.pid))"

stop:
	@if [ -f storage/engine.pid ]; then kill "$$(cat storage/engine.pid)" 2>/dev/null && rm storage/engine.pid && echo "engine stopped" || echo "engine was not running"; else echo "no engine pid recorded"; fi

# The console's generic lab actions drive start/stop; `up` is the human alias.
start: up
# The generic lab page polls a monitor frame; the engine status is the frame.
monitor: status

status:
	@if [ -x "$(ENGINE)" ]; then echo "engine: built ($(ENGINE))"; else echo "engine: not built — run make setup"; fi
	@curl -fsS "http://127.0.0.1:$(PORT)/healthz" 2>/dev/null && echo || echo "engine: not running on $(PORT)"

open: $(ENGINE)
	@if [ -z "$(URL)" ]; then echo "usage: make open URL=https://example.com"; exit 2; fi
	@curl -fsS -X POST "http://127.0.0.1:$(PORT)/api/web/windows" -d '{"url":"$(URL)"}' \
	  || { echo "engine not reachable — run make up first"; exit 1; }

events:
	@curl -fsS "http://127.0.0.1:$(PORT)/api/web/events?since=0" || { echo "engine not reachable — run make up first"; exit 1; }

test:
	cd $(BROWSER_DIR) && $(CARGO) test

clean:
	cd $(BROWSER_DIR) && $(CARGO) clean
