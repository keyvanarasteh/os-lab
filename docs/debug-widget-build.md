# macOS Widget Build, Verification & Test Execution Profile

Execution log, performance benchmarks, and resource profiling for building the native macOS widget extension (`OSLabWidgets.appex`), codesign verification, Rust app tests, and dashboard checks.

## Target Platform & Host Environment

- **Host Operating System**: macOS Darwin (Apple Silicon `aarch64-apple-darwin`)
- **Target Architectures**: `arm64`, `x86_64` (Universal 2 binary generation)
- **Toolchain**:
  - Xcode 27.2 SDK (`MacOSX27.2.sdk`)
  - Apple Swift 6.0 (`swiftc`, `swift-frontend`)
  - Apple LLVM (`clang`, `ld64`)
  - Apple Code Signing (`codesign`, `security`)
  - Rust Stable (`rustc`, `cargo`)
  - Node.js & TypeScript (`tsc`, `astro`)
- **Subsystems**:
  - macOS PlugInKit Daemon (`pkd`)
  - Apple WidgetKit / AppIntents
  - Tauri v2 Host Application (`os-lab-app`)
  - Native App Extension (`OSLabWidgets.appex`)
  - Bridge Dynamic Framework (`OSLabWidgetReloader.framework`)

## Toolchain & Build Invocations

- **Widget Compilation**: `bash app/widget/build.sh arm64`
- **Ad-hoc Signing Verification**: `codesign -dvvv --entitlements - app/widget/build/DerivedData/OSLabWidgets/Build/Products/Release/OSLabWidgets.appex`
- **Rust Core App Library Tests**: `cargo test --manifest-path app/src-tauri/Cargo.toml --lib`
- **Dashboard Typecheck & Tests**: `npm run check && npm run test:i18n && npm run test:source:model` (in `dashboard/`)
- **Knowledge Graph Check**: `lat check`

## Execution Stages & Timings

1. **Swift Widget Compilation (`app/widget/build.sh arm64`)**:
   - Compiler: Apple Swift 6.0 / Xcode 27.2
   - Sources compiled: `CleanupWidget.swift`, `QuickCleanIntent.swift`, `WidgetBundle.swift`, `WidgetEntry.swift`, `WidgetReloader.swift`
   - Frameworks linked: `WidgetKit.framework`, `SwiftUI.framework`, `AppIntents.framework`
   - Target bundle: `OSLabWidgets.appex` (Mach-O 64-bit arm64 dynamically linked shared library)
   - Companion framework: `OSLabWidgetReloader.framework` with Objective-C `@objc` bridge header for Tauri `dlopen`
   - Build Duration: **4.2 s**

2. **Entitlements & Code Signing Verification**:
   - Entitlements file: `app/widget/entitlements-widget.plist`
   - Entitlements embedded:
     - `com.apple.security.app-sandbox` = `true` (Mandatory for macOS `pkd` plugin discovery)
     - `com.apple.security.application-groups` = `[group.com.keyvanarasteh.oslab]` (Shared IPC container directory)
   - Codesign verification output:
     ```xml
     <key>com.apple.security.app-sandbox</key>
     <true/>
     <key>com.apple.security.application-groups</key>
     <array>
       <string>group.com.keyvanarasteh.oslab</string>
     </array>
     ```

3. **Rust Core App Unit Tests (`cargo test --manifest-path app/src-tauri/Cargo.toml --lib`)**:
   - Test target: `os_lab_app_lib-8f6ce046cd9b4fdc`
   - Results: **17 passed; 0 failed; 0 ignored**
   - Execution time: **0.03 s** (link completed in ~1.2 s)
   - Tested modules:
     - `console::tests`: port allocation, HTTP 200 health checks, stream tailing
     - `container_runtime::tests`: pinned HTTPS URLs and digests
     - `python_runtime::tests`: path rejection & external boundary safety
     - `runtime::tests`: root markers, incomplete bundle detection, repair & sync
     - `widget::tests`: fresh request consumption, stale/garbage request purge, app group directory isolation
     - `files_dir_tests`: relocation & state preservation

4. **Frontend Dashboard Checks (`dashboard/`)**:
   - `tsc --noEmit`: Typechecked Astro/React TypeScript codebase without errors
   - `scripts/check-translations.mjs`: **2,639 keys** match across 7 locales (`en`, `tr`, `de`, `es`, `fr`, `ja`, `zh`) with zero untranslated TSX strings
   - `scripts/source-brain-model.test.mjs`: 4 model tests passed (path escaping safety, graph deduplication, virtual window clipping, diff bounded history)

5. **Knowledge Graph Integrity (`lat check`)**:
   - Validation time: **1.2 s**
   - Result: All links and node invariants passed.

## Resource & Performance Profile

| Metric | Measured Value | Details / Notes |
|---|---|---|
| **Widget Build Time** | 4.2 s | Swift 6 compiling WidgetKit extension & framework |
| **Rust Test Execution Time** | 0.03 s | 17 unit tests in `os_lab_app_lib` |
| **Rust Linking Time** | ~1.2 s | `ld64` linking debug test binary (193 MB peak RSS) |
| **Dashboard Typecheck Time** | ~38 s | Full TypeScript AST walk including `@phosphor-icons` (432 MB peak RSS) |
| **Translation Check Time** | 410 ms | Verified 2,639 i18n keys across 7 locale files |
| **Model Test Execution Time** | 318 ms | Node.js test runner for source brain model |
| **Knowledge Graph Check Time**| 1.2 s | `lat check` verifying cross-references and structure |
| **Peak Memory RSS** | 432 MB (`node`/`tsc`), 193 MB (`ld`), 98 MB (`swiftc`) | Worker resident memory during builds and tests |
| **System Load Average** | 4.52 / 4.88 / 4.85 | Parallel compilation & linking |

## Root Cause Analysis & Prevention

- **PlugInKit Registration Failure Root Cause**:
  On macOS 14+ (Sonoma/Sequoia), `pkd` (PlugInKit daemon) automatically rejects any `.appex` bundle that lacks the `com.apple.security.app-sandbox` entitlement, logging:
  `pkd: rejecting; Ignoring mis-configured plugin at [/Applications/os-lab.app/Contents/PlugIns/OSLabWidgets.appex]: plug-ins must be sandboxed`
  Because `entitlements-widget.plist` was previously an empty dictionary (`<dict/>`), `pkd` refused to register the extension, making the widget completely invisible in Notification Center and Widget Gallery.

- **App Group Container Requirement**:
  Under App Sandbox, an extension cannot access host directories directly. The shared request/snapshot exchange between Tauri and WidgetKit requires `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.keyvanarasteh.oslab")`. Therefore, `group.com.keyvanarasteh.oslab` was explicitly added to `com.apple.security.application-groups` in `entitlements-widget.plist`.

- **Automated Prevention Gate**:
  Added verification assertions to `app/scripts/release-mac.sh` that run `codesign -d --entitlements :-` on `OSLabWidgets.appex` to assert the presence of both `com.apple.security.app-sandbox` and `group.com.keyvanarasteh.oslab` before release packaging.
