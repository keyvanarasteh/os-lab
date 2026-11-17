# ios-lab on macOS

Native path: Xcode + iOS Simulator + Appium XCUITest. This is the supported
Apple stack and the only practical path on Apple Silicon.

## Setup

```bash
cd ..
make mac-doctor
make mac-setup
make mac-setup INSTALL=1   # Homebrew + Node + Appium + XCUITest
bash ios-lab/mac/appium.sh install   # only Appium: no sudo, installed under ~/.oslab/appium
```

The dashboard's **Install Appium** button (macOS Lab page, or This computer) runs `appium.sh install` with a step-by-step progress bar. It installs Node with Homebrew only if Node 20.19+/22.12+ is missing, then Appium and the XCUITest driver into `~/.oslab/appium` (override with `OSLAB_APPIUM_HOME`); no administrator rights or global npm directory. `appium.sh start` and the host tool check use that copy, or one already on `PATH`.

`mac-setup` never installs Xcode itself. Install Xcode from the App Store or
Apple Developer downloads, open it once, accept the licence, and install a
simulator runtime from **Xcode > Settings > Components**.

Configuration lives in `config.env` (copied from `config.env.example`):

```bash
SIM_DEVICE="iPhone 16 Pro"
IOS_RUNTIME=latest
APPIUM_HOST=127.0.0.1
APPIUM_PORT=4723
APPIUM_LOG=artifacts/appium.log
BOOT_TIMEOUT=300
```

Use a preset:

```bash
make mac-profiles
make mac-profile PROFILE=iphone
make mac-profile PROFILE=ipad
make mac-profile PROFILE=legacy
```

## Lifecycle

```bash
make mac-sim
make mac-status
make mac-appium
make mac-appium-stop
make mac-stop
```

The simulator scripts use `xcrun simctl`. `run-simulator.sh` falls back to the
first available iPhone when the configured device is not installed.

## Notes

- Xcode and the Simulator are large; keep 30 GB+ free.
- Appium XCUITest builds WebDriverAgent on first use; the first session is
  slower and may need Xcode signed in.
- A physical iPhone needs a development team and provisioning profile.
- Simulators are not a security boundary; use a dedicated user or disposable
  VM for untrusted apps.
- For CI, use a real macOS runner with Xcode rather than the Linux container
  path.

### Real devices and Xcode location

The dashboard's iOS Actions card, simulator panel and `make mac-doctor` report two things the
simulator scripts alone never could:

- **Real devices** — paired or connected iPhones and iPads, listed read-only
  via `xcrun devicectl` (simulator rows are filtered out). The Actions card
  checks the current connection tunnel automatically; a paired phone whose
  tunnel is unavailable appears dimmed as Offline. Selecting a connected
  real device in the simulator panel captures its screen with `xcrun devicectl
  device capture screenshot`, without WebDriverAgent. Actually driving the
  device still needs Developer Mode and a WebDriverAgent signed to your team
  (a free personal team works for a first run; the existing Appium XCUITest
  stack drives it once WDA is installed).
- **Where Xcode lives** — detection follows `xcode-select`/PATH, never an
  assumed install path. An Xcode installed on another volume (e.g.
  `/Volumes/Apps/Applications/Xcode.app`) is detected wherever it is and the
  doctor prints the resolved `xcodebuild` path; the drawer shows the app
  location.
- **Storage pressure** — when the system disk runs low, the drawer points at
  the Cleanup Lab's Relocation tab, which can move
  `~/Library/Developer/CoreSimulator/Devices` to another volume behind a
  verified symlink (close Xcode and Simulator first — the owning-app lock
  refuses the move while they run). Simulator runtimes are system-managed and
  cannot be relocated this way.
