# Privacy

Morphwheel runs on your computer and keeps your files there. This page says what it stores, what it
reads, and the one network request it can make. Everything here describes the code as released;
the paths are the app's own (`src/morphwheel/settings/paths.py`).

## No telemetry, no accounts

Morphwheel collects no usage data, has no account, and contacts no server of its own. There are no
third-party analytics, crash reporters or update checks.

## Network: one opt-in request

Morphwheel makes no network connection unless you ask for the HEIC engine. When you choose
**Install…** under *HEIC support* in Settings, the app shows this consent text first (the
command-line switch `morphwheel --install-heic` is itself the request and downloads at once):

> Morphwheel downloads pillow_heif-… (… MB) from PyPI and keeps it in your profile, for you only.
> pillow-heif is open source under the GPLv2; Morphwheel itself stays MIT.

If you accept, it downloads one file, the pinned `pillow-heif` wheel, from PyPI's file host
(`files.pythonhosted.org`) over HTTPS, verifies its SHA-256 against the value built into the app, and
unpacks it into `%LOCALAPPDATA%\Morphwheel\engines\heic\`. The request carries no identifier beyond what
any download does. Nothing is uploaded. *Remove* in the same place deletes the engine.

## What is stored, and where

| What | Where | Notes |
|---|---|---|
| Settings | `%APPDATA%\Morphwheel\settings.toml` | the trigger key, wheel size, quality, Compress preset, start with Windows, pause, onboarding done, language, and which plugins are enabled and in what order |
| Plugins | `%APPDATA%\Morphwheel\plugins\` | folders you put there |
| Logs | `%LOCALAPPDATA%\Morphwheel\logs\` | rotating text files; see below |
| Engines | `%LOCALAPPDATA%\Morphwheel\engines\` | the opt-in HEIC download |
| Converted files | beside the source file | or in `Downloads\Morphwheel` when the source folder is not writable |
| Start with Windows | the registry value `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Morphwheel` | written only when the option is on; removed when it is off or at uninstall |

The uninstaller removes the app and the registry value, and asks (default *No*) whether to delete the
settings, plugins, logs and engines too. Converted files are never touched.

## The logs

The log records what the app did and how long it took: the gesture and the drop, the conversion
jobs, their results, errors with tracebacks, and timings. Lines carry **file names, and sometimes
full paths** (for example the folder an engine was unpacked into, or a path inside an error). The
log never leaves your computer unless you attach it to a bug report yourself. *Open log folder* in
the tray menu shows the files.

## What the app reads on your system

To detect a drag and show the wheel, Morphwheel:

- **Registers for raw mouse input** (Windows' Raw Input, with the *input sink* flag), so it sees
  mouse button presses and releases, and mouse motion while a gesture is being tracked, even while
  File Explorer owns the drag. It reads the cursor position at those moments.
- **Polls the trigger key** (Shift by default) with `GetAsyncKeyState` while a press is being
  tracked, at 8 ms intervals. Only the key's up/down state is read.
- **Looks at the window under the cursor** at the press: its window class chain, to decide whether
  it is File Explorer or the Desktop, and its process's integrity level, to refuse drags from
  sandboxed (lower-integrity) processes.
- **Reads the dragged files** it is given through the drop: their names and the first bytes of each,
  to tell the format.

There is no keyboard hook, no keystroke logging and no screen capture. The clipboard is written
only when you click *Copy* in a dialog, and never read. Mouse and key state are used in the moment
and are not stored (the log records the gesture's outcome, not the input stream).

## Deleting everything

Uninstall and answer *Yes* to the data question, or delete `%APPDATA%\Morphwheel` and
`%LOCALAPPDATA%\Morphwheel` yourself. Files you converted stay where they were created.
