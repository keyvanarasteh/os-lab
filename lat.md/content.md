# Content updates

Data that changes between app releases (Firewall Lab companies, guides, legal
documents and the Frida hooks) is published as a signed content pack that the
console downloads on request.

## What is in a pack

A pack has two classes, and only files under the allowed roots can be in it.

`data` is the Firewall Lab companies, catalog, schema, knowledge and templates,
the iOS knowledge notes and `docs/legal`. `hooks` is the Frida scripts in
`android-lab/lab/hooks`; they run inside other processes, so they are installed
only when the person ticks that box, every time. Code (`labctl`, the console,
the lab scripts) is never in a pack: it ships with the app. The allowed roots
and suffixes are `CLASSES` in [[console/content.py]]; the builder and the client
both apply them.

## Trust

The manifest is signed with an Ed25519 key that is not in the repository, and
the client checks that signature before believing anything in it.

[[scripts/build-content.py]] lists each file with its SHA-256 and size, hashes
the pack, and signs the exact bytes of `manifest.json`. [[console/content.py]]
holds the public key, verifies in pure Python (RFC 8032), then checks every
member of the pack against the manifest. An unlisted file, a wrong hash or size,
a link, an unsafe path, a bad pack hash or a missing file rejects the whole
update, and nothing is installed in place: files are staged and swapped. A
manifest older than the installed one is refused. Downloads are HTTPS only and
size-capped.

The private key is `secrets/content/content-signing.pem` on the maintainer's
machine and the `CONTENT_SIGNING_KEY` repository secret. Losing it means
shipping a new app with a new public key, so back it up.

## Where it lives and how it is read

Downloaded files go to `OSLAB_CONTENT_DIR` (the app sets it to its data folder,
`labctl ui` defaults to `~/.oslab/content`), beside the bundled copy rather than
over it. `reset` deletes the overlay and the bundled files are used again.

The console serves `/api/content/status`, `/companies`, `/file?path=` (content
paths only) and the POSTs `check`, `update` (`{"hooks": true}` to include hooks)
and `reset`; `/api/hooks` reads the downloaded hooks only when they were
installed. Nothing contacts the network except `check` and `update`, and
`OSLAB_CONTENT_OFFLINE=1` switches even those off.

## Publishing

[[.github/workflows/content.yml]] validates every PR and, on master, signs and
replaces the `content-latest` release (plus an archived `content-<sequence>`).
[[scripts/publish-content.sh]] does the same from a maintainer's machine. The
sequence number is the commit count, so it only goes up.

Tests: [[android-lab/lab/tests/test_content.py]] and the content cases in
[[android-lab/lab/tests/test_web_ui.py]].

## In the dashboard

The "Content updates" panel on the host page ([[dashboard/src/views/content-panel.tsx]]) shows the
state and drives check, update (hooks only when the checkbox is ticked) and reset.

[[dashboard/src/firewall/live.ts]] replaces the seeded companies with the downloaded ones at run time
when a pack is installed, and [[dashboard/src/views/not-found-page.tsx]] draws a company that has no
prerendered page from the pack. Without a console or a downloaded pack, the seed is used.

## Proof and the info page

Contributors can show their change works with a verification report and an optional
recording; the instructions live in [[docs/CONTENT.md]], which the dashboard renders at
`/content/`.

[[scripts/verify-content.py]] runs the CI checks and lists each changed content file with its
class and SHA-256; CI prints it in the job summary. Recordings are attached to the pull
request, never committed. `python3 console/content.py` is the terminal client for status,
check, update and reset.
