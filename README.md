# Morphwheel

**Shift-drag a file in Windows File Explorer, drop it on a wheel, get it converted.**

> **Status: pre-alpha, under construction.** Nothing is ready to download yet.

Start dragging an image in File Explorer and press **Shift**. A wheel of formats appears around your
cursor. Drop the file on a format, and a new converted file is created next to the original. No app
window opens.

## Promises

- **Your original file is never touched.** Morphwheel never moves, overwrites or deletes a source file.
  Every drop is accepted as a copy, outputs are always new files, and each source is checked after
  every conversion.
- **Local and private.** There is no telemetry. Nothing leaves your computer unless you opt in to an
  engine download, such as HEIC support.
- **Extensible in Python.** The built-in converters use the same plugin API that you can use to write your own.

## Planned for v0.1

- Image conversion between JPG, PNG, WebP, AVIF, ICO and PDF, plus a one-drop *Compress*.
- HEIC/HEIF input, as an opt-in download. Its codec library is GPL-licensed, so it is not bundled
  with the installer.
- Windows 11. Windows 10 22H2 is best-effort.

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

HEIC input needs the opt-in engine: `.venv\Scripts\python.exe -m morphwheel --install-heic` downloads the
pinned pillow-heif wheel (GPLv2, never bundled) into `%LOCALAPPDATA%\Morphwheel\engines`.

Run the development wheel from source with `.venv\Scripts\python.exe -m morphwheel --debug`. It shows the
wheel on a Shift-drag from File Explorer and logs the drop; conversions arrive in the next sprint.

Design documents, decisions and progress are in [`docs/`](docs/README.md).

## License

[MIT](LICENSE). Third-party components keep their own licenses. Qt for Python (PySide6) is LGPLv3.
