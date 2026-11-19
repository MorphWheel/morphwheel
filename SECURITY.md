# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | the latest 0.1 release |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting: open the
repository's **Security** tab and choose **Report a vulnerability**. We aim to acknowledge reports
within a few days and to say what we will do within two weeks.

## What we consider in scope

- Anything that lets Morphwheel **modify, move or delete a source file**, or overwrite an existing
  file.
- Code execution through a crafted input file, for example through an image decoder.
- Bypassing the plugin trust prompt, or loading plugin code into the main (GUI) process.
- The opt-in engine download (HEIC): integrity, hash pinning, and download location.
- The installer and the release pipeline: a way to install as administrator, to tamper with what the
  workflow publishes, or a mismatch between the published installer and its checksum.
- Anything that lets a lower-integrity (sandboxed) process open the wheel or drive a conversion.

Out of scope: plugins you chose to enable (they are your code, running as you), and attacks that
need an already compromised user account.

## The safety model

Each rule below is enforced in code and covered by tests; the decision IDs refer to
[`docs/decisions.md`](docs/decisions.md).

- **Every drop is a copy.** Under Shift, Windows proposes a *move*, and File Explorer would delete
  the source after a successful drop. Every drag event on the wheel is forced to *copy* before
  anything else happens.
- **Outputs are new files.** An output path is reserved with an exclusive create, written to a
  temporary file, and committed by rename. Nothing is ever opened for writing on an existing file,
  and a source is never modified, moved or overwritten.
- **Sources are fingerprinted.** Size, modification time and the NTFS file id are recorded before a
  conversion and checked after it; a source that changed under the app is reported, not retried.
- **Conversions run in worker processes**, in a fixed pool, with a 120-second limit per task. A
  crashed or hung worker is replaced. The workers are a separate, Qt-free executable. This
  isolation is for stability; it is not a sandbox.
- **Plugins are disabled until you enable them** (a prompt names the plugin and its folder and
  warns that it runs as you). Plugin code never runs in the GUI process; the app reads only a
  plugin's `plugin.toml`. A plugin is one module or package resolved inside its own folder, and it
  cannot shadow the app's own modules, Pillow's or Python's (decision RD-28).
- **No elevation.** Started with a full administrator token, the app offers to restart normally and
  otherwise quits; it never runs elevated. The installer and the uninstaller refuse likewise, and
  install for the user only.
- **Lower-integrity drag sources are refused** (RD-8): the pressed window's process integrity level is
  compared with the app's own.
- **Undo is limited** to the file Morphwheel created, sent to the Recycle Bin, and only if it is
  unchanged since conversion.
- **Decompression bombs** are refused by the image decoder's limit rather than decoded.
- **The HEIC engine** is downloaded only on your request, from a pinned URL on PyPI's file host, and
  installed only if its SHA-256 matches the value built into the app.

## Release integrity

- Every release ships `SHA256SUMS.txt` beside the installer; the release workflow verifies the
  checksums of what it publishes.
- Code signing through SignPath Foundation is applied for. Until it is approved, releases are
  **unsigned**; once it is, the two executables and the installer are signed, and the installer's
  uninstaller stub stays unsigned (a known limitation of the signing step).
- The release workflow publishes on a tag push only, grants `contents: write` to the publishing job
  alone, pins every third-party action to a commit, and never bundles the GPL-licensed HEIC codecs.

## Plugins are code

A Morphwheel plugin is Python code that runs with **your** user permissions. Plugins are disabled
until you enable them, and they run in separate worker processes. That isolation is for stability,
not for security. Only enable plugins from sources you trust.
