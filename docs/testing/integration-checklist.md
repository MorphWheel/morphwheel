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
- **Animations are off over RDP** (Windows' switch), so the fades and the appear animation never run there. Start
  the app with `--motion on` to force them for C28 and C29; the 60 fps check (C30) needs a local console.
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
| C15 | Hub repeats the target (C5) | C13, but hover JPG, then PNG, then the center before dropping | The hub reads `→ JPG`, then `Already this format` (PNG onto a PNG), then `Cancel` under the Fluent dismiss icon (RD-36); the hovered slot is highlighted | S2 |
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
| C28 | Drop during the appear animation (M2 #1) | Start the app with `--motion on`. Shift-drag a PNG copy and drop it on JPG **at once**, within the 167 ms appear animation (press Shift and release in one motion) | `wheel shown … motion on`, `DragEnter`, `DropRequest … -> jpeg`, `hide: dropped`; the JPG is created and the source is unchanged. The floor catches from the first frame: nothing falls through to Explorer | S4 |
| C29 | After the fade, nothing catches (M2 #9) | With `--motion on`: open the wheel, move out of the halo so it fades (`hide: left_halo`), move back to where the wheel was and release there, over the same Explorer folder | No `DragEnter` and no `DropRequest` after `hide: left_halo`; Explorer handles the release itself (a drop in the source folder does nothing). Esc instead of releasing is the safe variant | S4 |
| C30 | Motion and look | On a **local console** (not RDP), `--motion auto`: open the wheel, hover slots, open More (hover NW for 250 ms), drop; repeat in Light and in Dark, and once with S and L from `apply_size` (S5 settings; until then `--debug` only) | Appear: scale 0.94 → 1 with a fade-in; labels replace the skeleton at DragEnter; the hovered slot turns accent and stands 4 px proud, the hub repeats `→ JPG`; the arc grows outward; the dropped slot flashes, then the wheel shrinks and fades; a release over the hub fades at once. No stutter in Explorer's drag image (M2 #6). Over RDP (`motion off`) every change is instant and nothing moves | S4 |
| C31 | High Contrast and a scheme switch | Turn on a Windows High Contrast theme, open the wheel; turn it off, switch Light ↔ Dark in Settings, open the wheel again | High Contrast: opaque disc, 2 px borders, system colors, no shadow (`theme high_contrast`). After the switch the next wheel logs the new `theme` and uses the other token set | S4 |
| C32 | Toast buttons without focus (M2 #7) | Put the cursor in Explorer's search box, drop a PNG copy on JPG, wait for the toast, click **Show in folder**, then drop another copy and click **Undo**; with two monitors, drop on the second one | The toast appears bottom-right of the monitor of the drop, above the taskbar; the search box keeps the caret and Explorer stays the active window while the buttons work. Show in folder opens the output's folder with the file selected (`reveal photo.jpg: ok`); Undo sends the JPG to the Recycle Bin (`undo … recycled`) and the toast becomes `Moved to Recycle Bin`. ✕ closes a toast; a click on its text does not | S5 |
| C33 | The working toast | Drop 12 PNG copies on WebP; then drop one large PNG (≥ 20 MP) on AVIF | The batch shows `Converting 12 files to WebP…` with a bar and `n / 12` at once; the single file shows `Converting <name> to AVIF…` only if it runs longer than a second, and never for a quick file. ✕ on the batch toast hides it for good: later progress shows nothing, the result does. With `--motion on`: toasts rise 12 px while fading in and fade out; over RDP they appear and vanish at once, and the batch shows `n / 12` as text with no bar | S5 |
| C34 | The tray icon | Start the app; hover the tray icon; right-click it; choose Pause, drop a file, choose Pause again; drop 12 PNG copies on WebP and watch the icon; run the tampering plugin case (C24) and click the icon; choose Open log folder; switch Windows' mode (Settings → Personalization → Colors → "Choose your mode") and drop a file; choose Quit | The icon is a white wheel on a dark taskbar (near-black on a light one) with the tooltip `Morphwheel — Shift-drag to convert` (the key follows the setting). Paused: a dimmed wheel with ‖, tooltip `Morphwheel — paused`, no wheel on a Shift-drag (`paused` in the log), and `paused = true` in `settings.toml`. Working: a bright arc walks around the ring at 8 fps (over RDP: a fixed dot), tooltip `Converting n / 12…`. After the tampering case: a red dot, tooltip `1 problem — click for details`; a left click opens the details and clears the dot. Open log folder opens `%LOCALAPPDATA%\Morphwheel\logs` in Explorer. After the mode switch the next icon repaint uses the other ink. Quit removes the icon at once (no ghost icon until the mouse passes over it) | S5 |
| C35 | The settings window | Tray → Settings…: change the trigger key to Ctrl, drop a file with Ctrl held; pick Small, open the wheel; drag the JPG quality slider while watching `settings.toml`; type 1600 in Longest side and press Tab; switch Windows to Hebrew display language later (S5 file 8) for the mirror check; press Esc; open it again from the tray while a wheel is up (Shift-drag, then click the tray with the other hand) | A normal window with focus and the native Windows 11 style; the tray tooltip says `Ctrl-drag` at once and the wheel opens on Ctrl; the wheel is smaller on its next show (U4, RD-16); the file changes once per slider gesture, not per pixel; the spin box commits on Tab; Esc hides the window and the tray brings the same one back; while a drag is in progress nothing opens (`settings window not opened: a drag is in progress`) | S5 |
| C36 | First run (M2 #8) | Delete `%APPDATA%\Morphwheel\settings.toml`, start the app and wait a second; with the bubble up, Shift-drag a PNG copy near the bottom-right corner and drop it on JPG; delete the file again, restart, click **Settings** on the bubble; delete, restart, click **Got it**; delete, restart, quit from the tray with the bubble up, start again | The bubble appears bottom-right above the taskbar, never taking focus, with the accent stripe: `Morphwheel is running` / `Drag an image in File Explorer, then press Shift.` (the key from the settings) and two buttons. The wheel opens above it and the drop lands; the bubble fades and only the result toast remains. **Settings** opens the settings window on General, in front (a click on a no-activate window must still bring it forward). After Got it, Settings or a drop the bubble never returns (`onboarding_done = true` in the file); after a quit with the bubble up it does. Check the glyph before the title renders as a ring, not an emoji | S5 |
| C37 | HEIC support in the app (A6) | With no engine installed (delete `%LOCALAPPDATA%\Morphwheel\engines\heic` if present; the dev venv must not have pillow-heif importable: run the frozen build), Shift-drag a `.heic` copy; after the wheel hides, click **Install** on the toast, read the consent, press Return, then click **Install**; wait; Shift-drag the `.heic` again onto JPG; open Settings → Conversion, click **Remove**; drop a partial batch (C24) and click **Details**; tray → About | The hub says `Needs the HEIC engine`; the toast `HEIC support isn't installed.` with the size appears once per run; Return on the consent cancels (Cancel is the default); Install starts `Installing HEIC support…` after a second (not for a fast download), then `HEIC support installed`; the next `.heic` drag converts without a restart (`catalog refreshed: missing engines none`); the Conversion page says Installed with a Remove button; Remove says `HEIC support removed` (with `The files still in use go at the next start.` right after a HEIC conversion); Details opens a plain window with the whole list, Copy copies it, Esc closes it; About opens the settings on About. The consent and the Details window come to the front from a toast click | S5 |
| C38 | Start with Windows and one instance | On the frozen build: turn the General page's toggle on, read `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` in `regedit`; sign out and in; in Task Manager → Startup apps, disable Morphwheel, open the settings; turn the toggle on again; turn it off. Then start `morphwheel.exe` a second time while it runs; from a second user session (if available) start it too. Run the elevated case (C21) and watch the restarted instance | The Run value holds the quoted exe path; the app is in the tray after the sign-in; after Task Manager's Disable the toggle reads off, turning it on clears the Disable (Task Manager says Enabled) and the value is rewritten; off deletes the value. A second start shows no second tray icon and opens (or brings forward) the settings of the running one; `already running: asked it to open the settings (True)` in the second start's log. Another session gets its own instance. After "Restart normally" exactly one instance runs | S5 |
| C39 | A right-to-left language (D3a) | Compile a Hebrew catalog (`.venv\Scripts\python.exe tools\translations.py update he`, translate a few strings in the `.ts`, then `release`), build so the `.qm` is bundled, set `language = "he"` and `onboarding_done = false` in `settings.toml`, start the app; open the settings from the tray, convert a file, open the HEIC consent, read the tray menu, drag a file. Then remove the setting and start again | The settings window, the toasts, the bubble, the dialogs and the tray menu are mirrored, with the translated strings in Hebrew and Latin file names at the right edge under the title; Qt's Cancel reads ביטול; the wheel is unchanged (slots in their places); the log says `language: he (right-to-left)`. Without the setting, on an English Windows, everything is English and left-to-right even though the catalog is there | S5 |
| C42 | Install, autostart, Launch, upgrade (S7 file 2) | Quit Morphwheel in every session (check Task Manager for `morphwheel-worker.exe`). Run `morphwheel-<version>-setup.exe`: no UAC prompt; the folder offered is `%LOCALAPPDATA%\Programs\Morphwheel`; the "Automatically start Morphwheel" box is unchecked. Tick it, finish with "Launch" ticked. Then start the app and run the installer again while it runs. Then right-click the installer, "Run as administrator" | The app starts in the tray as you (Task Manager: not elevated). `HKCU\...\Run\Morphwheel` holds the exe path, quoted only if the path has a space; Settings shows "Start with Windows" on. The second run says Morphwheel is running and offers Retry/Cancel (quit from the tray, Retry: it upgrades in place, the box is pre-ticked from the registry). The elevated run is refused with a message and installs nothing | S7 |
| C43 | Uninstall (S7 file 2) | With a plugin under `%APPDATA%\Morphwheel\plugins\` and a file in `Downloads\Morphwheel\`, uninstall from Settings > Apps while the app is quit. Answer No to the data question. Reinstall, uninstall again, answer Yes | After No: the app folder, the Start menu entry and the Run value are gone; `%APPDATA%\Morphwheel` (settings, the plugin) and `%LOCALAPPDATA%\Morphwheel` stay. After Yes: both folders are gone; `Downloads\Morphwheel\` and its file stay | S7 |
| C41 | The folder rule on the frozen build (RD-28) | On the frozen build, put a plugin in `plugins\x.utils\` whose `plugin.toml` says `entry = "utils:Converter"` beside a `utils.py` with a converter; Rescan, enable it through the prompt, Shift-drag a PNG onto its target. Then rename the module and the entry to `x_utils` and repeat | The first conversion fails with a plugin error whose detail says `'utils' resolves outside the plugin's folder` (the frozen app bundles a module of that name ahead of any plugin folder); the renamed plugin converts. The log holds both outcomes | S6 |
| C44 | The wheel's Fluent icons (RD-36) | On the frozen build, drag a JPG with Shift and look at the wheel in Light, in Dark, and in a High Contrast theme, at sizes S, M and L (Settings → General), and once at 150 % scaling if a monitor allows. Hover Compress, PDF and More, then the hub; drag a `.mp4` once. | Compress, PDF and More show a small icon centred above their label, and the hub shows the dismiss icon above `Cancel`. Each icon has its label's color: dimmed with it on the `.mp4`, the accent's text color on hover, the system text color in High Contrast. No icon is clipped, blurred or overlaps its label, and no other slot moved. | S7 carry-over |
| C40 | The Plugins page and the trust prompt (S6) | Copy `examples/sample_plugin` into `%APPDATA%\Morphwheel\plugins\sample_plugin\`, open Settings → Plugins, click Rescan. Tick the row: press Return, then Esc. Tick again, click Enable. Shift-drag a PNG. Copy a second plugin, Rescan, drag one row above the other with the mouse; then Alt+Down on the current row. Untick a row. Click Open plugins folder. Put a folder with no `plugin.toml` in, and a junction to another folder (`mklink /J`), Rescan. With a Hebrew catalog in effect (C39), open the page | The row appears unchecked after Rescan. The prompt names the plugin and its folder; Return does nothing (Cancel is the default), Esc closes it and the row stays unchecked; after Enable the row is checked, `settings.toml` holds `enabled`, and the target is in the More arc at the next drag. After the mouse drag the arc order follows at the next drag and `settings.toml` holds `order`; Alt+Down moves the row and writes once. Unticking shows no prompt and the target leaves the arc. Explorer opens the plugins folder. The folder without a manifest and the junction are listed under the broken folders with their reasons; neither is enableable. The page mirrors: check boxes and buttons on the right, rows in Hebrew, Latin names kept as runs | S6 |

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
(`python -m morphwheel --debug`) and reads `morphwheel.log`. It drives rows C13–C20 and, since
2026-11-26, C23; C21 (UAC) and C22 (the mouse-button setting) stay by hand.

Since S3 the drops convert for real, so the driver also reads the engine's lines: C13 and C14 check
the Compress job (`success` or `already_compact`), C19 the WebP job (`2 file(s) -> webp (1 skipped)`,
`success`). **C23** drops `mw-test-a.png` on JPG (north) and checks the job line, the output line,
`job … finished: success`, a success toast, and the file itself: new beside the source (not left by
an earlier run), the logged size, a real JPEG, and the source's sha256 unchanged. JPG sits north, over
the command bar when the item is in the first row, so the wheel is opened low enough in the item
list for the JPG point to be inside it, and the run stops with Esc if it isn't. Outputs are left in
`%TEMP%\morphwheel-dragtest` and listed as `outputs_created` in the results; empty that folder by
hand after a few runs, or later rows can scroll out of view and stop the run. The checks run offline
in `tests/qt/test_wheel_driver.py` against the lines the dispatcher and the toast manager really
write, each with a negative control.

```bash
.venv\Scripts\python.exe tools\wheel_driver.py --dry-run
.venv\Scripts\python.exe tools\wheel_driver.py --rows C23
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
| A4 | `morphwheel.exe --worker-check` on the frozen build: every worker reports `morphwheel-worker.exe` and `qt_loaded=False` (A5a), and `wheel icons: OK` (RD-36) | S3 |
| A5 | `pytest -m integration`: real worker processes, crash and timeout, the tampering plugin, a deny-ACE folder | S3 |
