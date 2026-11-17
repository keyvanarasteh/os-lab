# Release automation

The app version in `app/package.json`, `app/src-tauri/Cargo.toml` and
`app/src-tauri/tauri.conf.json` must agree before creating `app-v<version>` at the intended commit.
Release workflows only publish assets for that tagged commit. Each workflow can also be run
manually without publishing, to inspect its build artifacts.

| Workflow | Output | Automatic tag publishing |
|---|---|---|
| `release-linux` | amd64 and arm64 Debian, RPM and AppImage packages, with SHA-256 files | yes |
| `release-win` | x64 NSIS and MSI, with SHA-256 files | yes, unsigned until SignPath is configured |
| `release-mac` | universal signed and notarized DMG, with SHA-256 file | after Apple secrets and `MACOS_RELEASE_CI_ENABLED=true` are set |
| `updater-manifest` | signed artifact URLs for the in-app updater | manual, after all platform installers are published |

The Linux workflow runs on pull requests touching app or dashboard files. It installs, launches
under Xvfb, and removes each Debian package before publishing. Windows CI installs, launches and
uninstalls the MSI. The macOS workflow uses
`app/scripts/release-mac.sh`, which verifies both the app and DMG signatures and notarization.

## App updater

The desktop app checks `app-updates/latest.json` when the user chooses **File → Check for app
updates**. It installs only updater bundles signed by the public key in `tauri.conf.json`, with
the signature bound to the announced version. The private key is stored in the repository secret
`TAURI_SIGNING_PRIVATE_KEY`; a local backup is in ignored `secrets/updater/os-lab.key`. Preserve
an additional secure backup outside the repository and worktrees. Losing the private key prevents
updates to existing app installations. The matching public key is tracked in
[`UPDATER_PUBLIC_KEY.pub`](UPDATER_PUBLIC_KEY.pub), with a decoded minisign copy in
[`UPDATER_MINISIGN.pub`](UPDATER_MINISIGN.pub) for manual verification. Never commit or print
the private key.

The platform builds publish `.sig` files alongside their updater bundles. On Windows, the
SignPath-signed installer is signed again with the Tauri key, because Authenticode changes its
bytes. Debian, RPM and DMG downloads also have detached signatures for manual verification;
apt and dnf do not treat those as repository signatures. After every macOS, Windows and Linux
asset is present on `app-v<version>`, run the
`updater-manifest` workflow with that version. It verifies the SHA-256 files and refuses to
publish a partial platform set. The feed is stored in the `app-updates` prerelease so content
releases cannot accidentally become the app update endpoint. A release is not available through
in-app update until this step succeeds.

## macOS signing setup

Add these repository secrets for the `release-mac` workflow:

- `APPLE_CERTIFICATE`: base64 encoded Developer ID Application `.p12`, including its private key
- `APPLE_CERTIFICATE_PASSWORD`: password used to export that `.p12`
- `KEYCHAIN_PASSWORD`: temporary CI keychain password
- `APPLE_API_KEY_P8`: contents of an App Store Connect API `.p8` key
- `APPLE_API_KEY`: App Store Connect key ID
- `APPLE_API_ISSUER`: App Store Connect issuer ID

After a manual `release-mac` run builds and notarizes successfully, set repository variable
`MACOS_RELEASE_CI_ENABLED` to `true`. Future `app-v*` tags then publish automatically. Until then,
the local signed release command remains `app/scripts/release-mac.sh --publish`.

Never commit certificate or key files. The workflow writes the temporary key into the runner's
private temporary directory and the runner is discarded after the job.

## Telegram notifications

The release workflows (`release-mac`, `release-win`, `release-linux`) and `updater-manifest`
report their outcome to Telegram when the repository secrets `TELEGRAM_BOT_TOKEN` (a bot token
from [@BotFather](https://t.me/BotFather)) and `TELEGRAM_CHAT_ID` (the chat to post into) are
set; send the bot any message and read `getUpdates` once to learn the chat id. Without the
secrets the reporting step skips silently and nothing else changes. Reports cover real builds
only — tag and manual runs — never pull-request dry runs, and the scheduled 20-minute
safety-net runs of `updater-manifest` stay quiet. A Telegram failure never fails the release:
the send step continues on error.

## Windows signing setup

Until SignPath is configured, every `app-v*` tag publishes unsigned installers (SmartScreen
warns) and the release notes state the code-signing policy. Follow [SIGNING.md](SIGNING.md) to
enroll the project in SignPath Foundation and configure `SIGNPATH_API_TOKEN` and
`SIGNPATH_ORGANIZATION_ID`; from the next tag on, the workflow signs through SignPath, verifies
both Authenticode signatures and publishes those instead, with no workflow change. A valid
signature helps establish trust; SmartScreen reputation may still take time to build.

## Release order

1. Merge and test all release changes.
2. Set the intended version, then create and push `app-v<version>` on that exact commit.
3. Inspect the workflow results and release assets. Do not mark the release complete until the
   macOS, Windows and Linux files and SHA-256 checks are present.
4. Run `updater-manifest` for the new version and verify `app-updates/latest.json` contains all
   five platform entries. Exercise the update from the previous app version on each OS.
5. Install and launch at least one file on each OS; record any platform limitation in the release
   notes and [INSTALL.md](INSTALL.md).
