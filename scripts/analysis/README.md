# Offline extension analysis

## PENT-18: Native messaging host risk analyzer

`ext_native_host.py` audits an owned unpacked extension and explicitly supplied
native host manifests. Python 3.11+; standard library only. No browser, Docker,
Frida, registry access, network connection or native host execution is needed.

Create **inert, locally owned fixtures** (destination must not already exist):

```bash
python3 scripts/analysis/make_native_host_lab.py /tmp/pent18-lab
```

Use the fixture ID (32 lowercase letters `a`) for `--extension-id`:

```bash
ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
python3 scripts/analysis/ext_native_host.py /tmp/pent18-lab/safe/extension \
  --lab-root /tmp/pent18-lab --host /tmp/pent18-lab/safe/host.json --extension-id "$ID"
python3 scripts/analysis/ext_native_host.py /tmp/pent18-lab/risky/extension \
  --lab-root /tmp/pent18-lab --host /tmp/pent18-lab/risky/host.json --extension-id "$ID" --json
```

Exit codes: **0** no findings at the selected threshold; **1** review-worthy
findings at/above threshold; **2** invalid, oversized, unreadable or out-of-scope
input. Default threshold is `--fail-on high`; `medium` and `never` are available.
Code 0 means the selected static checks found no high risks, not a security
certification. Repeat `--host` to inspect several manifests.

The declared `--lab-root` bounds all input reads after resolving links.
References outside it are reported without reading the binary; out-of-scope
input files fail the scan. Keep the lab directory private and unchanged while
scanning: this tool does not defend against concurrent malicious file swapping.
Directory links/junctions in the extension are refused. Limits are 500 files,
100 host manifests, 1 MiB per JSON, 2 MiB per source and 32 MiB per binary;
exceeding a limit refuses the scan instead of producing a partial clean report.

Checks include required/optional nativeMessaging permissions; lexical
`chrome/browser.runtime.connectNative/sendNativeMessage` calls and file/line
clues; unresolved computed host names; host name/type/description; Chromium
`allowed_origins` and Firefox `allowed_extensions`; explicit caller matching;
missing and out-of-scope binaries; SHA-256, size and PE/ELF/shebang headers;
POSIX group/world write and setuid/setgid bits in the contained host path.

Chromium identity must be supplied, because an unpacked extension's effective
ID cannot reliably be guessed. Firefox identity is read from
`browser_specific_settings.gecko.id` or legacy `applications.gecko.id`.
Linux/macOS require absolute host paths; Windows permits paths relative to the
host manifest (`--platform windows`). Binary inspection on another platform is
reported as unverified. Windows ACLs are explicitly unverified; POSIX mode bits
do not prove effective ownership, ACL safety or elevated execution.

JavaScript matching is **lexical**, not an AST or data-flow analysis. Comments
and strings can match, aliases/bracket notation/computed names can be missed,
and a call does not prove runtime reachability. Header checks do not establish
binary validity or signatures. A bridge is a capability, not evidence of malware;
browser registration and host message validation need separate review.

Reports go to stdout; redirect JSON to a private output file when needed.
No data is sent or stored automatically. Reports contain scoped file paths,
host names, file hashes and finding locations; review before sharing.

Tests (also included in the repository's normal runner):

```bash
python3 -m pytest android-lab/lab/tests/test_ext_native_host.py -q
./scripts/run-tests.sh
```

References: [Chromium native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
and [Firefox native manifests](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests).
