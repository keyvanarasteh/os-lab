# OS-24 Local .deb Installer - Verification

## Environment
- OS: Ubuntu Server 26.04.1 LTS
- Shell: Bash
- Project: os-lab
- Task: OS-24 Local .deb Installer

## Purpose
This script installs a local Debian (.deb) package on Ubuntu.

## Verification Plan
1. Check Bash syntax.
2. Test missing arguments.
3. Test nonexistent package files.
4. Test invalid .deb packages.
5. Test installation preview and confirmation.
6. Verify successful package installation.

## Test Results

### Test 1 - Bash Syntax
Command: bash -n linux-lab/scripts/deb_install.sh
Result: PASS - No syntax errors.

### Test 2 - Missing Argument
Command: bash linux-lab/scripts/deb_install.sh
Result: PASS - Usage message displayed.

### Test 3 - Missing Package File
Command: bash linux-lab/scripts/deb_install.sh olmayan-paket.deb
Result: PASS - Missing package was rejected.

### Test 4 - Invalid Package
Command: touch sahte.deb && bash linux-lab/scripts/deb_install.sh sahte.deb
Result: PASS - Invalid package was rejected.

### Test 5 - Real Package Installation
Package: hello
Command: bash linux-lab/scripts/deb_install.sh hello_*.deb
Result: PASS - Package installation completed.

### Test 6 - Installation Verification
Command: dpkg -s hello | grep Status
Output: Status: install ok installed
Result: PASS - Package installation verified.

## Faz 2 - Windows UI Automation and Safe Control

### Live services
Console command: `.venv-test\Scripts\python.exe android-lab\lab\web_ui.py 5050`
Result: PASS - `http://127.0.0.1:5050/api/health` returned `status=ok`.

Dashboard command (from `dashboard/`, using the installed Node 24.20.0 executable because Node was not on PowerShell `PATH`): `& "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.20.0-win-x64\node.exe" node_modules\astro\bin\astro.mjs dev --host 127.0.0.1 --port 4321 --strictPort`
Result: PASS - `/labs/winapps/` returned HTTP 200 and its `/api` proxy reached the live console.

### Live UI Automation
Target: a locally created, non-sensitive `OSLab UIA Verification` window.

Command: `GET /api/labs/winapps/apps/3214182/elements`
Result: PASS - HTTP 200, `engine=uia`, 9 visible elements, and a revision token.

Command: `GET /api/labs/winapps/apps/3214182/search?q=Safe%20action`
Result: PASS - HTTP 200, one `Button` match labelled `Safe action`.

Playwright against the live dashboard and console:
- PASS - the UIA hotspot and search displayed the live `Safe action` result.
- PASS - arm and disarm state transitions reached the live `/control` endpoint.
- PASS - the preview dialog and enabled confirmation were displayed.
- PASS - no `/click` or `/input` request was sent; the preview was cancelled.
- PASS - mirrored window pixels were blurred in the evidence image.

Evidence: [winapps-uia-controls.png](docs/media/screenshots/winapps-uia-controls.png)

### Automated Test Results
Command: `python -m pytest -q tests/test_winapps.py tests/test_web_ui.py` (from `android-lab/lab/`)
Result: PASS - 66 passed.

Command: `python -m pytest tests` (from `android-lab/lab/`)
Result: PARTIAL - 607 passed, 83 skipped, 5 failed. The failures were outside WinApps: a Docker availability assertion, two Windows content/encoding checks, and two macOS parity checks (including an Accessibility-permission check).

Command: `node scripts/check-translations.mjs` (from `dashboard/`)
Result: PASS - 2,867 keys match across 7 locales; no new untranslated TSX strings.

Command: `node_modules/.bin/tsc --noEmit` (from `dashboard/`)
Result: PASS.

Command: `node_modules/.bin/astro build --outDir .phase2-build` (from `dashboard/`)
Result: PASS - build completed; Vite reported a large-chunk warning.

Command: `scripts/e2e.sh --changed`
Result: WinApps scenarios passed. One full run had 75 passed and 1 skipped; the latest run had 74 passed, 1 skipped, and 1 unrelated `lab-switcher` locator failure.

Command: `lat check`
Result: PASS.

## Phase 3 - Windows App Mirror Advanced Interactions

### Automated Test Results
Command: `.venv-test\Scripts\python.exe -m pytest -q android-lab\lab\tests\test_winapps.py android-lab\lab\tests\test_web_ui.py` (from the repository root)
Result: PASS - 79 passed.

Command: `.venv-test\Scripts\python.exe -m pytest -q tests` (from `android-lab\lab`, with `PYTHONUTF8=1`)
Result: PARTIAL - 622 passed, 83 skipped, 3 failed. The failures were outside WinApps: the Docker cleanup test could not detect its fake engine in the Windows environment, and two macOS parity tests require macOS `osascript`/Accessibility permissions.

Command: `npm run test:i18n` (from `dashboard/`, with Node 24.20.0 on `PATH`)
Result: PASS - 2,871 keys match across 7 locales; no new untranslated TSX strings.

Command: `npm run check` (from `dashboard/`)
Result: PASS - TypeScript completed without diagnostics.

Command: `npm run build -- --outDir .phase3-build` (from `dashboard/`)
Result: PASS - 540 pages built. Vite reported its existing large-chunk warning; the temporary `.phase3-build` output was removed.

Command: `bash -c 'python3() { python "$@"; }; source scripts/e2e.sh --changed'` (Git Bash, from the repository root, with Node 24.20.0 on `PATH`)
Result: PASS - 76 passed, 1 skipped.

Command: `lat check`
Result: PASS - all checks passed (with a warning that no `lat init` version is recorded).

### Live Windows Verification
Target: a disposable local WinForms window titled `OSLab Phase 3 Verification` with a harmless `Safe action` button (HWND `2755402`).

- `GET /api/labs/winapps/apps`: PASS - the real verification window was listed at 440×240 physical pixels, 96 DPI.
- `GET /api/labs/winapps/apps/2755402/screenshot`: PASS - HTTP 200, `image/png`, 5,848 bytes, valid PNG signature.
- `GET /api/labs/winapps/apps/2755402/stream?fps=2`: PASS - HTTP 200, `multipart/x-mixed-replace`, first frame contained a valid PNG.
- `GET /api/labs/winapps/apps/2755402/elements`: PASS - UI Automation returned 8 visible elements and a revision token.
- `GET /api/labs/winapps/apps/2755402/search?q=Safe%20action`: PASS - one matching `Safe action` button.
- Dashboard with the live console: PASS - the UIA hotspot/search, arm lock, recent-action audit, and double-click review dialog worked. The preview was cancelled; no `/click` or `/input` request was sent. The control lock was disarmed afterward.

Evidence: [winapps-advanced-parity.png](docs/media/screenshots/winapps-advanced-parity.png)
