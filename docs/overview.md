# Morphwheel: overview

> One page with everything you need to know about the app.
> The **source of truth** is the approved discovery docs in [`discovery/`](discovery/), which are in Hebrew.
> This page summarizes them and links back. Decisions live in [`decisions.md`](decisions.md).

## What it is

**Morphwheel** is an open-source (MIT) Windows alternative to the macOS app Tangerine.

1. Start dragging a file in File Explorer.
2. Press **Shift**.
3. A wheel of formats appears around the cursor.
4. Drop the file on a format. A **new file** is created next to the original, and **the source is never
   touched**.

What sets it apart from existing clones (P1-1):
- **Safety first:** forced Copy, never overwrite, and a source integrity check.
- A **configurable trigger**.
- **Python plugins**.
- **Signed builds**.

## Scope of v0.1 (MVP)

| In | Out (after v0.1) |
|---|---|
| Image conversion. Inputs: JPG, PNG, WebP, AVIF, BMP, TIFF, static GIF, and HEIC as an *opt-in download* (A6) | Video and audio (FFmpeg, v0.2) |
| Outputs: JPG, PNG, WebP, AVIF, ICO and PDF, plus Compress | Documents, animated images, folders |
| Drag sources: File Explorer and the Desktop | Virtual files (zip, Outlook), browsers |
| A toast with Show in folder and Undo, a tray icon, settings | Keyboard navigation, context-menu entry, Store |
| Python plugins in the user's folder, shown in the More arc | Plugin catalog, pip |
| Windows 11 (Windows 10 is best-effort) | |
| English UI with i18n infrastructure; Hebrew comes next (D3, D3a) | Other languages |

Details: [Phase 2 §3–§4](discovery/phase-2-concept.md).

## How it looks

- **8 fixed slots** (U2):

  | Slot | Content |
  |---|---|
  | N | JPG |
  | NE | PNG |
  | E | WebP |
  | SE | AVIF |
  | S | Compress |
  | SW | PDF |
  | W | ICO |
  | NW | More (plugins) |

- **Center hub:** cancels the drop, and repeats the hovered target.
- **Behavior:**
  - **Sticky (U1):** the wheel stays open after Shift is released.
  - **Catch halo (U1):** a drop near the wheel cancels.
  - **Back to a normal drag (U1):** move out past the halo.
  - **Arming (U7):** a slot can be selected only after the pointer moves 12 px.
- **Theme:** light and dark follow Windows, with the system accent color. Color tokens and motion
  durations come from WinUI. Everything also works with animations off.
- **No app window in the flow.** Toasts appear in the bottom-right corner.

Details and ASCII wireframes: [Phase 3](discovery/phase-3-ux.md).

## How it is built

| Module | Folder | Role |
|---|---|---|
| Core | `src/morphwheel/core/` | Every behavioral rule. No Qt, no Win32. |
| OS hooks | `platform/` | Raw Input, modifier polling, Win32 |
| GUI | `ui/` | Wheel, toasts, tray, settings |
| Conversion engines | `engine/`, `builtin/` | A pool of 2 worker processes; the built-in Pillow converter |
| Extensions | `plugins/` | Public API (stdlib-only) and `plugin.toml` |

There are two kinds of process:
- **GUI process:** handles input, and returns from a drop in under 5 ms.
- **Worker processes:** run the conversions. They are the only place plugin code runs.

import-linter enforces these boundaries in CI. Contracts and the traceability table are in [Phase 4](discovery/phase-4-architecture.md).

## Stack

| | |
|---|---|
| Runtime | Python 3.12 |
| GUI | PySide6-Essentials 6.12.0 (LGPL) |
| Images | Pillow 13.0.0 (built-in AVIF) |
| HEIC | pillow-heif 1.8.1, **opt-in download only** (GPLv2) |
| Settings | platformdirs, tomllib, tomli-w |
| Quality | pytest and pytest-qt, ruff, mypy (strict), import-linter |
| Packaging | PyInstaller (onedir), Inno Setup (per-user), SignPath (signing), winget |

## Milestones

| Milestone | Sprints |
|---|---|
| M0 Foundation | S0 |
| M1 Core engine | S1–S3 |
| M2 Overlay UI | S4–S5 |
| M3 Extension system | S6 |
| M4 Release v0.1 | S7 |

Live status: [`progress.md`](progress.md).

## Technical facts worth remembering

- **In File Explorer, Shift+drag means Move.** Without `force_copy`, Explorer deletes the source after the drop.
  Qt proposes Move under Shift on both the windows and the offscreen platforms (verified in S0).
- **A window shown in the middle of a drag** receives DragEnter within 9–51 ms. This was measured in the spike,
  over RDP.
- **Pixels with alpha 0 let drops pass through.** Every catching area must have alpha 1 or more.
- **PyInstaller's PySide6 runtime hook loads QtCore into every process started from the main exe.** The workers
  therefore run from a second, Qt-free executable, `morphwheel-worker.exe` (A5a); `morphwheel.exe --worker-check`
  proves it on a frozen build.
- **An output is never written over anything.** The worker claims the output name with an exclusive create held
  open with delete-on-close, writes a temp file beside it, and renames the temp at the end; a rename never
  replaces an existing file (RD-10).
- **Explorer sends no drag WinEvents**, and does not publish the dragged files on the clipboard.
- **Environment:** the user works over RDP, where Windows animations are off. Real drag tests need an
  active interactive session.
