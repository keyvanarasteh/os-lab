# secrets

Release credentials live here **on the build machine only**. Everything in this folder except this
README is git-ignored, and `release-mac.sh`, `release-win.ps1` and `release-deb.sh` refuse to run if anything else in it is tracked.

```text
secrets/cupertino/
  app-store-connect/
    AuthKey_<KEYID>.p8     # App Store Connect API key (notarization)
    key-id.txt             # or keyId.key
    issuer-id.txt          # or IssuerId.key
  apple/                   # only when the certificate is not in the login keychain
    developer-id-application.p12
    developer-id-application.p12.password
```

```text
secrets/windows/           # only for the optional Authenticode signing in release-win.ps1
  thumbprint.txt           # SHA-1 thumbprint of a certificate already in the user's store (or a hardware token)
  os-lab.pfx               # or the certificate with its private key...
  os-lab.pfx.password      # ...and its password (imported into the user's store at build time)
  timestamp-url.txt        # e.g. http://timestamp.digicert.com (that is also the default)
```

The Debian package is unsigned and needs nothing from here. Windows variables: `OSLAB_WIN_CERT_THUMBPRINT`,
`OSLAB_WIN_TIMESTAMP_URL`, `OSLAB_SECRETS_WIN_DIR` (another folder laid out like `secrets/windows`).

Resolution order for each value: environment variable → this folder → a sibling
`../qLar/secrets` checkout (read-only, never copied) → the login keychain (signing identity only).

| Variable | Meaning |
| --- | --- |
| `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Name (TEAMID)`; found in the keychain if unset |
| `APPLE_API_KEY`, `APPLE_API_ISSUER`, `APPLE_API_KEY_PATH` | notarization (key id, issuer id, `.p8` path) |
| `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD` | base64 `.p12` and its password, for a machine without the certificate in its keychain (CI) |
| `OSLAB_SECRETS_DIR` | another folder laid out like `secrets/cupertino` |

On GitHub Actions, put the same names in repository **secrets**; never in the workflow file.

```text
secrets/content/
  content-signing.pem      # Ed25519 private key that signs the content pack (scripts/build-content.py)
```

Its public half is `PUBLIC_KEY` in `console/content.py`; the same PEM is the `CONTENT_SIGNING_KEY` repository
secret that `.github/workflows/content.yml` signs with. Back it up: without it, content can only be updated by
shipping an app with a new public key. Variables: `OSLAB_CONTENT_SIGNING_KEY` (the PEM text),
`OSLAB_CONTENT_SIGNING_KEY_FILE`.
