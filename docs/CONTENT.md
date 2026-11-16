# Content updates

os-lab can update some of its material without a new app release: the Firewall Lab
companies and catalog, the guides, the legal documents and, only if you choose, the Frida
hook scripts. This page explains what updates, how to use it, why it is safe, and how
contributors prove that their change works.

## What updates and what never does

| Class | What | Installed |
|---|---|---|
| **data** | Firewall Lab companies, catalog, schema, knowledge and templates; iOS knowledge notes; `docs/legal` | when you press update |
| **hooks** | Frida scripts in `android-lab/lab/hooks` | only when you ask for hooks, every time |
| never | `labctl`, the console, lab scripts, installers, the dashboard build | these ship with the app and change only with an app release |

Hook scripts run inside other processes with the privileges of the app you test, so they are
a separate choice and never arrive silently.

## How to use it

Opening **This computer** checks the small signed manifest when the last check is older than 15
minutes. The content pack itself downloads only after you press the update button.
`OSLAB_CONTENT_OFFLINE=1` switches off both checks and updates.

In the dashboard, open **This computer** and find **Content updates**. The compact card shows the
installed and latest versions. **Check and update** verifies the manifest and installs a newer
signed data pack, with progress status. **Advanced options** keeps the separate **Check for updates**,
**Update content**, **Include Frida hooks** checkbox (off every time), and **Reset to bundled**.
If hooks are already installed, the compact button opens Advanced options so you can make that
choice again before updating.
The Firewall Lab then lists the
downloaded companies; a company that is new in the pack opens from the same address, drawn from the pack.

From a terminal, in an os-lab checkout:

```bash
python3 console/content.py status            # what is installed, and the last check
python3 console/content.py check             # is there a newer signed pack? installs nothing
python3 console/content.py update            # install the newest data
python3 console/content.py update --hooks    # ...and the Frida hooks too
python3 console/content.py reset             # delete downloaded content, use the bundled copy again
```

The console serves the same actions to the dashboard under `/api/content/` (`status`,
`companies`, `file?path=`, and the POSTs `check`, `update` with `{"hooks": true}`, and `reset`).

Where the downloaded files go:

| How you run os-lab | Folder |
|---|---|
| Desktop app | its data folder, `content/` (macOS: `~/Library/Application Support/com.keyvanarasteh.oslab/content`) |
| `labctl ui` or the console | `~/.oslab/content` |
| anything | `OSLAB_CONTENT_DIR` if set |

Downloaded files sit beside the bundled copy, never over it, so `reset` always returns to
exactly what shipped. Use the same `OSLAB_CONTENT_DIR` for the terminal and the app if you
want them to share one overlay.

## Why it is safe

Every pack has a manifest listing each file with its SHA-256 and size. The manifest is signed
with an Ed25519 key that is not in the repository; the app contains only the public key. Before
installing, the client checks the signature, the pack hash, and every file. A file that is not
listed, has the wrong hash or size, is a link, or has an unsafe path rejects the whole update.
Files are staged and swapped in, an older pack than the installed one is refused, and downloads
are HTTPS only. Details and the key policy: `lat.md/content.md`.

A content update changes what you see (companies, guides, hook scripts). It does not change
what the app is allowed to run, and it adds no new network access beyond the check itself.

## How a contribution reaches users

1. You open a pull request that changes a content file (for example a company in
   `firewall-lab/companies/`).
2. CI validates the company schema, builds the pack and runs the client's own manifest checks.
3. A maintainer reviews and merges.
4. On merge to `master` the workflow signs a new pack and replaces the `content-latest` release.
5. Installed apps pick it up the next time their user checks for updates.

A merged mistake therefore reaches people only through that user-initiated check, and the
previous pack stays available as `content-<sequence>`.

## Proof for contributions

A reviewer can merge faster when they can see that your change works. None of this is
required, and it never replaces review; it is how you show your work.

**1. Verification report (recommended, takes seconds).** Run it in your branch and paste the
output into the pull request:

```bash
python3 scripts/verify-content.py
```

It runs the same checks as CI and lists every content file you changed with its class, size
and SHA-256, so the reviewer sees exactly what would ship. CI also prints this report in the
job summary. Use `--out proof.md` to keep a copy, or `--all` to cover every content file.

**2. A short video or animation (optional).** For a company or guide, a 10 to 30 second
screen recording of the dashboard showing your change is the clearest proof. For a hook, a
recording of it running in the lab against an app you own. Record with any screen recorder
(QuickTime, OBS, `Win+G`, GNOME's `Ctrl+Shift+Alt+R`, or `asciinema` for terminal work) and
export `.mp4`, `.webm` or `.gif`.

**3. Attach, do not commit.** Drag the file into the pull request description or a comment:
GitHub hosts it (about 10 MB for images and GIFs, 100 MB for video), or link a video you host.
Do not add videos to the repository: they bloat the history forever, and the verification
report warns if you do.

What proof must not contain: secrets, tokens, personal data, other people's names, and
anything from systems you were not authorized to test (see the
[Acceptable Use Policy](legal/ACCEPTABLE_USE.md)). Blur or crop before recording.

Hooks need more care. Say what the hook does, which app and version you tested it on, and
expect the reviewer to read every line, because hooks run inside other processes.

## Troubleshooting

| Message | Meaning |
|---|---|
| `The manifest signature does not match` | The pack was not signed by the os-lab key, or the download was altered. Nothing was installed. |
| `... does not match the signed manifest` | A file differs from what was signed. Nothing was installed. |
| `refusing to go back` | The published pack is older than the one you have. Use `reset` first if you really want the bundled copy. |
| `switched off` | `OSLAB_CONTENT_OFFLINE` is set. |
| `Could not download` | No network, or GitHub is unreachable. The bundled or last installed content keeps working. |

Contributing in general: [CONTRIBUTING.md](../CONTRIBUTING.md).
