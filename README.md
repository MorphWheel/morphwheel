# Morphwheel

**Shift-drag a file in Windows File Explorer, drop it on a wheel, get it converted.**

> **Status: v0.1 in preparation.** The first release is being packaged; until it is published,
> there is nothing to download, and the source builds and runs (see *Development*).

Start dragging an image in File Explorer and press **Shift**. A wheel of formats appears around your
cursor. Drop the file on a format, and a new converted file is created next to the original. No app
window opens; a small toast in the corner shows the result, with *Show in folder* and *Undo*.

Morphwheel is an open-source (MIT) Windows alternative to the macOS app Tangerine.

## Promises

- **Your original file is never touched.** Morphwheel never moves, overwrites or deletes a source file.
  Every drop is accepted as a copy, outputs are always new files, and each source is checked after
  every conversion.
- **Local and private.** There is no telemetry and no network use, unless you opt in to an engine
  download, such as HEIC support. See [PRIVACY.md](PRIVACY.md).
- **Extensible in Python.** The built-in converter uses the same plugin API you can use to write your
  own. See [docs/plugins.md](docs/plugins.md).

## Install

- **The installer:** download `morphwheel-<version>-setup.exe` from the
  [Releases](https://github.com/MorphWheel/morphwheel/releases) page and run it. It installs for
  your user account only, into `%LOCALAPPDATA%\Programs\Morphwheel`, and needs no administrator
  rights (it refuses to run as administrator). The optional *Start with Windows* box is off by default.
  `SHA256SUMS.txt` beside the installer lets you verify the download.
- **winget**, once the first stable release is published and accepted into the community
  repository:

  ```powershell
  winget install MorphWheel.Morphwheel
  ```

- **Code signing:** the first releases are unsigned while the application to SignPath Foundation is
  pending; Windows SmartScreen may warn about an unrecognized app. Verify the checksum instead.

Windows 11 is supported; Windows 10 22H2 is best-effort. 64-bit only.

## Use

1. Start dragging one or more image files in File Explorer or on the Desktop.
2. Press **Shift**. The wheel appears at the cursor: **JPG, PNG, WebP, AVIF, Compress, PDF, ICO** and
   **More** (your plugins). The wheel stays open after you release Shift.
3. Drop on a slot. A slot that cannot take the dragged files is disabled and says why.
   Dropping in the center cancels; moving out past the wheel returns to a normal drag.
4. The toast shows the result. *Undo* sends the new file to the Recycle Bin (only the file Morphwheel
   created, and only if it is unchanged since).

Inputs: JPG, PNG, WebP, AVIF, BMP, TIFF and static GIF, plus HEIC/HEIF with the opt-in engine.
*Compress* writes a smaller copy, resized to a 2048 px longest side, and keeps it only if it is
actually smaller.

The tray icon has *Pause Morphwheel*, *Settings…*, *Open log folder*, *About Morphwheel* and *Quit*.
Settings cover the trigger key (Shift, Ctrl or Ctrl+Shift), the wheel size, the quality per format,
the Compress preset, *Start with Windows* and the plugins. The UI language follows Windows; it can
be set in `settings.toml` (there is no picker yet).

### HEIC and HEIF

HEIC input is an opt-in download. In **Settings › General › HEIC support**, choose *Install…*: after a
consent dialog, Morphwheel downloads the pinned `pillow-heif` wheel from PyPI, verifies its SHA-256
and keeps it in your profile (`%LOCALAPPDATA%\Morphwheel\engines\`). It is never part of the
installer, because its wheel bundles GPL-licensed codecs; Morphwheel itself stays MIT. *Remove* in the
same place deletes it.

### Plugins

A plugin is a folder with a `plugin.toml` and a converter module, under
`%APPDATA%\Morphwheel\plugins\`. Plugins are disabled until you enable them on the *Plugins* page, and
they run as your user in a worker process, so only enable plugins from sources you trust.
[docs/plugins.md](docs/plugins.md) has a converter in thirty lines, the contract, and the rules.

## Privacy and security

- [PRIVACY.md](PRIVACY.md): what the app stores, what it reads, and the one opt-in network request.
- [SECURITY.md](SECURITY.md): how to report a vulnerability, and the safety model.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): every bundled component and its license.
- [CHANGELOG.md](CHANGELOG.md).

## Development

Requires Python 3.12 on Windows.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,heic]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy
.venv\Scripts\lint-imports.exe
```

Run from source with `.venv\Scripts\python.exe -m morphwheel`; `--debug` adds a verbose log on the
console, `--any-source` opens the wheel for drags from any window, and `--motion on` or `off` forces
animations (they follow Windows' *Animation effects* switch, which is off over Remote Desktop).
`--install-heic` installs the HEIC engine from the command line, and `--worker-check` is the
smoke test the release build runs.

Building the installer: `pyinstaller packaging/pyinstaller/morphwheel.spec`, then
`ISCC.exe packaging\inno\morphwheel.iss` (Inno Setup 6.3 or later). The release workflow in
`.github/workflows/release.yml` does the same on a tag.

Design documents, decisions and progress are in [`docs/`](docs/README.md).

## License

[MIT](LICENSE). Third-party components keep their own licenses, listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); Qt for Python (PySide6) is used under the LGPLv3.
