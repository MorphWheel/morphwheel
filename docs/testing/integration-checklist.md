# Integration checklist (manual drag tests)

Real Explorer drags can't run in CI, because they need a live, interactive desktop. This checklist is run
by hand at the end of every sprint, and it grows as features land. Results go into the sprint report
(`docs/sprints/`).

## Before you start

- Use an **active, unlocked desktop session**. Over RDP, the session window must be open and in focus.
- Run the probe from a normal terminal, **not as administrator**:
  - From source: `.venv\Scripts\python.exe tools\drag_probe.py`
  - Frozen build (S3 and later): `packaging\output\dist\morphwheel\morphwheel.exe --debug`. Build it with the
    command in `packaging/pyinstaller/morphwheel.spec`. The frozen probe is no longer built; the probe runs from source.
- **Only drag throwaway copies.** Make a test folder, for example `C:\Temp\mw-test\`, with a few copied
  images. While Shift is held, Explorer's own default is *Move*. If a test fails before the overlay
  catches the drop, Explorer may move the file.
- Logs go to `%LOCALAPPDATA%\Morphwheel\logs\drag_probe-drag-*.log`. When you're done, say which
  tests you ran; the log holds the evidence.
- The probe needs to see Shift go down **after** the drag starts. Pressing Shift before the click
  range-selects files in Explorer.
- **S2 rows (C13 and up) use the app itself**, not the probe. Its log is
  `%LOCALAPPDATA%\Morphwheel\logs\morphwheel.log`; `--debug` adds the per-press lines the rows quote. The
  app has no tray yet: stop it with Ctrl+C in its terminal.

## Checklist

| ID | Test | Steps | Expected (what the log shows) | Since |
|---|---|---|---|---|
| C1 | Basic Shift-drag | Drag a file in the test folder, press Shift, drop on a slot (e.g. JPG) | `SHOW`, then `ENTER` within ~100 ms, `DROP slot:JPG → CopyAction`, `source intact` | S0 |
| C2 | Stationary cursor | As C1, but keep the mouse still for 2 s after pressing Shift | `ENTER` arrives without any `move` lines before it | S0 |
| C3 | Cancel on hub | As C1, but release over the center ("cancel") | `leave` / no `DROP` to a slot, file unchanged, overlay hides on release | S0 |
| C4 | Desktop as source *(spike test 4)* | Put a copy on the Desktop and Shift-drag it from there | `down … chain=Progman > SHELLDLL_DefView > …`, `source_ok=True`, overlay shows | S0 |
| C5 | Clipboard can't leak *(spike test 5)* | Select a file and press Ctrl+C. Then Shift-drag a **different** file and drop on a slot | `ENTER`/`DROP` list the **dragged** file, not the copied one | S0 |
| C6 | Title bar / tab drag *(spike test 6)* | Drag an Explorer window by its title bar or a tab while pressing Shift | `source_ok=False`, **no** `SHOW` | S0 |
| C7 | No Shift | Drag a file without Shift and drop it back in the same folder | No `SHOW` | S0 |
| C8 | Esc | Shift-drag until the overlay shows, then press Esc and release | `esc` logged, drag cancelled by Explorer, no `DROP`, file unchanged | S0 |
| C9 | Elevated window | Open PowerShell **as administrator**. Click into it and move or click the mouse. Then do C1 with that window open | Shows whether `down`/`up` lines still appear while the elevated window is in front (record the answer). The `FG` line, logged 300 ms after `SHOW`, names the foreground window and whether it is elevated. C1 still passes. | S0 |
| C10 | Multiple monitors *(if available)* | Do C1 on each monitor, including one with different scaling | `SHOW … screen=<that monitor>`, and the overlay is centered on the cursor | S0 |
| C11 | Local console timing | Do C1 and C2 **at the physical machine** (not over RDP) | Compare `ENTER` latency with the RDP numbers (9–51 ms in the spike) | S0 |
| C12 | Frozen build | Do C1 with `drag_probe.exe` | Same as C1 | S0 |
| C13 | Dev wheel: basic Shift-drag | Run the app from source: `.venv\Scripts\python.exe -m morphwheel --debug`. Drag a PNG copy, press Shift, drop on JPG | `morphwheel.log`: `press at … allowed=True`, `wheel shown`, `DragEnter: 1 url(s), plan ok`, `DropRequest: 1 file(s) -> jpeg`. The source file is unchanged (from S3 on, a JPG appears beside it: C23) | S2 |
| C14 | Dev wheel: timing (criterion 2) | C13, five times | From the log timestamps: `wheel shown` ≤ 50 ms after the Shift sample, `DragEnter` ≤ 100 ms after `wheel shown` (p95 of the five) | S2 |
| C15 | Hub repeats the target (C5) | C13, but hover JPG, then PNG, then the center before dropping | The hub reads `→ JPG`, then `Already this format` (PNG onto a PNG), then `✕ Cancel`; the hovered slot is highlighted | S2 |
| C16 | Leave the halo, reopen | C13, but move the pointer well outside the ring, then press Shift again | The wheel hides when the pointer leaves the ring (`hide: left_halo`), and a new press of Shift shows it again | S2 |
| C17 | Release over the hub | C13, but release over the center | The wheel hides at once (`hide: cancelled`), no `DropRequest`, file unchanged | S2 |
| C18 | Esc | C13, but press Esc before releasing | `Esc pressed`; Explorer cancels the drag, which reaches the wheel as a DragLeave with the button still down, so it hides with `hide: left_halo`; no `DropRequest` | S2 |
| C19 | Mixed drag | Drag a PNG and a JPG together onto JPG | Hub: `→ JPG` with `1 skipped`; `DropRequest: 2 file(s) -> jpeg` | S2 |
| C20 | Unsupported drag | Drag a `.txt` copy, press Shift | Every slot dimmed, hub `⊘ Not supported`, no slot accepts the drop, release does nothing | S2 |
| C21 | Elevated start, "Restart normally" | Start the app from an **administrator** terminal | The warning dialog appears. *Restart normally* starts a normal instance (`restarted without elevation` in the log, a new `Morphwheel … starting` line from the new process) and the elevated one quits. *Quit* exits with code 3. Record what happens if the restart fails (the "Couldn't start a normal instance" message) | S2 |
| C22 | Swapped mouse buttons | Settings → Bluetooth & devices → Mouse → switch the primary button. Do C13 with the (now primary) right button. Switch back | `raw input registered (swapped buttons: True)`, and C13 passes with the right button | S2 |
| C23 | A real conversion | C13 with a PNG copy dropped on JPG | `job <id>: 1 file(s) -> jpeg`, `… photo.png -> photo.jpg (<n> bytes, <ms> ms)`, `job <id> finished: success`. A `photo.jpg` sits beside the source, which is byte-for-byte unchanged (compare sizes and dates). A toast `✓ Converted to JPG` with `photo.jpg · <size> → <size>` appears bottom-right and fades after 6 s; hovering it pauses the fade | S3 |
| C24 | Mixed drag with a skip | Drag a PNG and a JPG together onto JPG | `job … 2 file(s) -> jpeg (1 skipped)`; one new JPG; the toast reads `✓ 1 file converted to JPG` with `1 skipped — already JPG` | S3 |
| C25 | Already compact | Drop a small, already-compressed JPG (quality ≤ 60) on Compress | `… failed with not_smaller`, `finished: already_compact`; no new file, no temp file left; toast `✓ Already compact` | S3 |
| C26 | Read-only folder | Copy a PNG into a folder you can't write to (for example `C:\Program Files\<any>`, or a folder with a deny ACE), drop it on JPG | `… -> photo.jpg (…, fallback folder)`; the JPG is in `Downloads\Morphwheel`; the toast says `Saved to Downloads\Morphwheel — the source folder is read-only` | S3 |
| C27 | HEIC with the opt-in engine | Without the engine, drag a `.heic`: every slot dimmed, hub `Needs the HEIC engine`. Run `morphwheel --install-heic`, restart the app, drag it again onto JPG | First: `missing engines: heic` at start-up and `plan not_supported`. After the install: `HEIC engine installed in …`, the restarted app logs `missing engines: none`, and the conversion runs like C23 | S3 |

## Scripted run (synthetic, S0-2)

`tools/drag_driver.py` drives rows C1–C8 and C12 with injected input (`SendInput`) against the real
Explorer and OLE drag loop, while the probe logs. `tools/uia_helper.ps1` finds the file icons through
UI Automation and checks every press point first. Results are **synthetic**: they say nothing about
hand timing, the physical console (C11) or the UAC prompt (C9), and they don't close the 👤 rows.

Run it with the RDP window visible and your hands off the mouse and keyboard for about a minute:

```bash
.venv\Scripts\python.exe tools\drag_driver.py --dry-run
.venv\Scripts\python.exe tools\drag_driver.py
```

Its results land next to the probe logs as `drag_driver-*.json`. It refuses to start unless the
desktop is reachable, stops at the first failure, and only ever releases the mouse button over the
probe's wheel or over its own window's item list; anything else is cancelled with Esc first.

**2026-10-28, RDP, one monitor at 200 %, Windows 11 25H2.** One clean run, no retries, every
row's files unchanged (sha256), source probe then the frozen build:

| Row | Result | Evidence |
|---|---|---|
| C8 | ✅ synthetic | `esc` logged, `DragLeave (button down)`: Esc cancels the OLE drag, no `DROP` |
| C1 | ✅ synthetic | `ENTER` 12 ms after `SHOW`; `DROP slot:Compress → CopyAction`; `source intact` |
| C2 | ✅ synthetic | `ENTER` 12 ms after `SHOW` with no movement for 2 s |
| C3 | ✅ synthetic | release over the hub: no `DROP`, overlay hid on release |
| C5 | ✅ synthetic | after Ctrl+C on another file, `ENTER`/`DROP` list the dragged file only |
| C7 | ✅ synthetic | threshold crossed, no `SHOW` without Shift |
| C6 | ✅ synthetic | title-bar press: `source_ok=False` (`TITLE_BAR_SCAFFOLDING_WINDOW_CLASS`), no `SHOW` |
| C12 | ✅ synthetic | frozen `drag_probe.exe`: `ENTER` 59 ms after `SHOW`; `DROP slot:Compress → CopyAction` |
| C4 | not run | UI Automation on this machine exposes no desktop icons, so the press point can't be verified. 👤 |
| C9 | 👤 | needs the UAC prompt |
| C10 | n/a | one monitor |
| C11 | 👤 | the physical console |

The drops aim at the Compress slot (south) rather than JPG: at 200 % the JPG point sits above the
item list, over Explorer's command bar, and an echoed RDP cursor position there at press time could
have clicked a toolbar button. `SHOW` comes about 550 ms after the press because the script holds
still before pressing Shift; that number says nothing about the app.

## Scripted run against the app (synthetic, S2)

`tools/wheel_driver.py` reuses the driver's machinery but starts the app itself
(`python -m morphwheel --debug`) and reads `morphwheel.log`. It drives rows C13–C20; C21 (UAC) and
C22 (the mouse-button setting) stay by hand.

```bash
.venv\Scripts\python.exe tools\wheel_driver.py --dry-run
.venv\Scripts\python.exe tools\wheel_driver.py
```

**2026-10-29, RDP, one monitor at 200 %, Windows 11 25H2.** One clean run after a fix to the driver
itself (after Esc the wheel is already hidden, so the release goes over the item list). Every row's
files unchanged (sha256). The drops aim at Compress (south) and WebP (east) for the same RDP reason
as the S0 run:

| Row | Result | Evidence |
|---|---|---|
| C18 | ✅ synthetic | `Esc pressed`; Explorer's DragLeave arrived with the button down → `hide: left_halo`; no `DropRequest` |
| C13 | ✅ synthetic | `wheel shown` → `DragEnter: 1 url(s), plan ok` 10 ms later → `hover: slot:s hub=target compress` → `DropRequest: 1 file(s) -> compress, handled 0.6 ms after the drop` → `hide: dropped` |
| C14 | ✅ synthetic | six wheels: shown 1.9–8.1 ms after the Shift key went down (the poller samples every 8 ms); five DragEnters 10–15 ms after `wheel shown` (p95 15 ms). Criterion 2: ≤ 50 ms and ≤ 100 ms |
| C15 | ✅ synthetic | `hover: slot:n hub=target jpeg`, `hover: slot:ne hub=disabled png`, `hover: hub hub=cancel` |
| C16 | ✅ synthetic | outside the ring: `hide: left_halo`; Shift again: a second `wheel shown`; no `DropRequest` |
| C17 | ✅ synthetic | release over the hub: `hide: cancelled`, no `DropRequest` |
| C19 | ✅ synthetic | PNG + WebP onto WebP: `DragEnter: 2 url(s)`, `hub=target webp`, `DropRequest: 2 file(s) -> webp` (the WebP is skipped in the plan) |
| C20 | ✅ synthetic | a `.txt`: `DragEnter: 1 url(s), plan not_supported`, `hover: slot:s hub=not_supported -`, no `DropRequest`, hid on release |
| C21 | 👤 | needs the UAC prompt |
| C22 | 👤 | changes a system setting |

Two RDP facts the driver works around, and anyone scripting drags over RDP should know:
the client echoes earlier cursor positions back to the server for a while after injected moves
(a `GetCursorPos` read can jump back to where the cursor was), and a press that lands on an item's
padding starts a rubber-band selection, not a drag, so no DragEnter ever arrives.

## Automated checks (no desktop needed)

| ID | Check | Since |
|---|---|---|
| A1 | `force_copy` matrix: 126 combinations, never Move (`tests/unit/test_drop_guard.py`) | S0 |
| A2 | `drag_probe.py measure`: frozen cold start, memory, Qt modules in workers | S0 |
| A3 | Defender scan of the frozen build (`MpCmdRun -Scan -ScanType 3`) | S0 |
| A4 | `morphwheel.exe --worker-check` on the frozen build: every worker reports `morphwheel-worker.exe` and `qt_loaded=False` (A5a) | S3 |
| A5 | `pytest -m integration`: real worker processes, crash and timeout, the tampering plugin, a deny-ACE folder | S3 |
