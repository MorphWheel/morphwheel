# Progress tracker

> **Living file.** Update it after every finished task and at the end of every work session.
> A new session starts here.
>
> Legend:
> - `[x]` done · `[~]` in progress · `[ ]` open
> - 👤 = Yuval's action · 🔶 = assumption to verify

## Current state

| | |
|---|---|
| **Phase** | Phase 5: implementation |
| **Sprint** | S5 ✅ approved 2026-11-12 (the surrounding UI; M2). **S6 is next** (the plugin system, M3). S4 ✅ approved 2026-11-04, S3 ✅, S2 ✅, S1 ✅, S0 closed (S0-3) |
| **Current task** | S5 file 8 done (2026-11-12): `i18n/` (`translate`, the catalogs, the direction), the `language` setting, `tools/translations.py`; RD-15 to RD-24 approved with S5 on 2026-11-12 ([`docs/sprints/S5.md`](sprints/S5.md)). Next: S6 file 1, `plugins/discovery.py` |
| **Next** | S6 (the plugin system, M3), file by file. Carry-overs to S7 listed under S7. RF-7 and RF-11 still open; RF-13 closed in S4 |
| **Blocked on** | Nothing. Still open 👤, gating S7: C4, C9, C11, C21, C22 and the SignPath application; by-hand rows C23–C39 |
| **Next approval stop** | End of S6 (A2) |

## Discovery phases

| Phase | Doc | Status |
|---|---|---|
| 1: Research | [phase-1-research.md](discovery/phase-1-research.md) | ✅ approved 2026-10-19 |
| 1b: Spike | [phase-1b-spike-results.md](discovery/phase-1b-spike-results.md) | ✅ approved 2026-10-19 |
| 2: Concept & MVP | [phase-2-concept.md](discovery/phase-2-concept.md) | ✅ approved 2026-10-19 |
| 3: UX/UI | [phase-3-ux.md](discovery/phase-3-ux.md) | ✅ approved 2026-10-19 |
| 4: Architecture | [phase-4-architecture.md](discovery/phase-4-architecture.md) | ✅ approved 2026-10-19: green light for Phase 5 |

## Sprint board

| Sprint | Milestone | Size | Status |
|---|---|---|---|
| S0: Foundation | M0 | M | `[x]` closed 2026-10-29 (S0-3); C4/C9/C11 and SignPath carried as 👤 items to S7 |
| S1: Pure core | M1 | M | `[x]` ✅ approved 2026-10-19 |
| S2: OS hooks and dev wheel | M1 | M | `[x]` ✅ approved 2026-10-29 (C13–C20 synthetic; C21, C22 👤) |
| S3: Engine and built-in converter | M1 | L | `[x]` ✅ approved 2026-10-29 (C23–C27 👤) |
| S4: Final wheel | M2 | L | `[x]` ✅ approved 2026-11-04 (C28–C31 👤) |
| S5: Surrounding UI (toasts, tray, settings, bubble, dialogs, autostart, i18n) | M2 | L | `[x]` ✅ approved 2026-11-12 (C32–C39 👤) |
| S6: Plugin system | M3 | M | `[ ]` |
| S7: Release v0.1 | M4 | M | `[ ]` |

---

### S0: Foundation (M0)

**Files, in order:**
- [x] 1. `pyproject.toml`
- [x] 2. `.gitignore`, `LICENSE`, `README.md`, `SECURITY.md`, `PRIVACY.md`
- [x] 3. `src/morphwheel/__init__.py`, `__main__.py`, sub-package skeleton, `app/application.py` stub (filled in S2)
- [x] 4. `src/morphwheel/logs.py`
- [x] 5. `src/morphwheel/settings/paths.py`
- [x] 6. `src/morphwheel/ui/wheel/drop_guard.py` and `tests/unit/test_drop_guard.py` (126-case matrix)
- [x] 7. `tests/conftest.py` (+ `tests/unit/test_paths_and_logs.py`)
- [x] 8. `.github/workflows/ci.yml`
- [x] 9. `packaging/pyinstaller/morphwheel.spec` (+ `file_version_info.txt`)
- [x] 10. `tools/drag_probe.py`
- [x] 11. `docs/testing/integration-checklist.md`
- [x] Sprint report: [`docs/sprints/S0.md`](sprints/S0.md)

**Exit criteria:**
- [x] All local checks pass: ruff, mypy, lint-imports, pytest (132 passed)
- [x] CI is green on GitHub ([Actions](https://github.com/MorphWheel/morphwheel/actions)): about 1 minute on windows-latest
- [x] The `force_copy` matrix passes
- [x] Frozen-build measurements: worker cold start, idle memory, build size. Targets for criteria 5–6 are proposed in the report.
- [x] Integration checklist v1 executed. **Scripted run 2026-10-28 (S0-2, synthetic):** C1, C2, C3, C5, C6, C7, C8 and C12 ✅; see the checklist. Still real-hand items, carried to the S7 gate (S0-3):
  - [ ] Spike tests 4–6: C4 (Desktop as source) 👤; C5 and C6 ✅ synthetic
  - [ ] Esc: ✅ synthetic (C8); 👤 to confirm by hand
  - [ ] Elevated window in the foreground (C9)
  - [ ] Multiple monitors, if available
  - [ ] **Re-measure on a local console session (not RDP)**
  - [x] Defender scan: no threats
- [x] License audit of the frozen bundle: no pillow-heif inside ✅; license texts are missing, so S7 adds them
- [ ] 👤 SignPath application submitted (carried to the S7 gate, S0-3)

### S1: Pure core (M1)
*`catalog.py` moved before `jobs.py`, because `Task` carries a `Target`.*
- [x] `core/errors.py`
- [x] `core/formats.py`
- [x] `core/catalog.py`
- [x] `core/jobs.py`
- [x] `core/geometry.py`
- [x] `core/output_policy.py`
- [x] `core/gesture.py`
- [x] `core/wheel_session.py`
- [x] Unit tests for each file (145 new; 277 in total)
- [x] Sprint report: [`docs/sprints/S1.md`](sprints/S1.md)

### S2: OS hooks and dev wheel (M1)
- [x] `platform/_win32.py` (+ `tests/unit/test_win32.py`, 19 tests; contracts P1 and P2)
- [x] `platform/system.py` (+ `tests/unit/test_system.py`, 13 tests)
- [x] `platform/window_probe.py` (+ `tests/unit/test_window_probe.py`, 13 tests)
- [x] `platform/raw_input.py` (+ `tests/qt/test_raw_input.py`, 17 tests)
- [x] `platform/modifier_poller.py` (+ `tests/qt/test_modifier_poller.py`, 14 tests)
- [x] `ui/wheel/window.py` (basic renderer) (+ `tests/qt/test_wheel_window.py`, 23 tests)
- [x] `app/controller.py` (partial) (+ `tests/qt/test_controller.py`, 11 scenarios)
- [x] `app/application.py` (+ `tests/qt/test_application.py`, 6 tests)
- [x] "Restart normally" feasibility 🔶 → implemented (RD-6); 👤 proven by hand in C21
- [x] Carry-over from S1: DragEnter **always** goes through `force_copy` (`window.py`; tested)
- [x] Carry-over from S1: `more_center_deg` comes from `geometry.more_arc(center, screen, MORE_ARC_MAX)` (`show_at`)
- [x] Carry-over from S1: feed `GiveUp` to the gesture machine when the session reports `GAVE_UP` (`gave_up` signal → controller)
- [x] Sprint report: [`docs/sprints/S2.md`](sprints/S2.md)

**Exit criteria (phase-4 §9):**
- [x] "Restart normally" feasibility checked: implemented (RD-6). 👤 C21 proves the click.
- [x] Shift-drag from Explorer shows the dev wheel with a real slot plan: ✅ synthetic (C13, C15, C19, C20, 2026-10-29)
- [x] A drop creates a `DropRequest` in the log: ✅ synthetic (C13)
- [x] Timings: wheel ≤ 50 ms, DragEnter ≤ 100 ms p95: ✅ synthetic (C14: 8.1 ms max, 15 ms p95)
- [ ] 👤 C21 (Restart normally from an elevated start) and C22 (swapped buttons) by hand
- [x] Gates green: ruff, format, mypy, import-linter (R1, P1, P2), 422 tests

### S3: Engine and built-in converter (M1)
- [x] `plugins/api.py` (+ `tests/unit/test_plugins_api.py`, 3)
- [x] `plugins/manifest.py` (+ `test_manifest.py`, 30; the impostor builtin stays in the arc)
- [x] `engine/integrity.py` (+ `test_integrity.py`, 8; the fingerprint carries the NTFS file id)
- [x] `engine/file_ops.py` (+ `test_file_ops.py`, 12; delete-on-close placeholders, rename-only commits, RD-10)
- [x] `plugins/loader.py` (+ `test_loader.py`, 5; the `broken` fixture plugin)
- [x] `builtin/pillow_images/plugin.toml`
- [x] `builtin/pillow_images/converter.py` (+ `tests/integration/test_converter.py`, 67)
- [x] `engine/worker_main.py` (+ `test_worker_main.py`, 13; the tampering plugin → SOURCE_CHANGED)
- [x] `engine/worker_pool.py` (+ `test_worker_pool.py`, 5, real processes: crash, timeout, respawn)
- [x] `engine/dispatcher.py` (+ `tests/qt/test_dispatcher.py`, 5)
- [x] `platform/shell.py` (+ `test_shell.py`, 2; recycle refuses drives without a Recycle Bin; Downloads via `platformdirs` in `settings/paths.py`)
- [x] `engine/undo.py` (+ `test_undo.py`, 6)
- [x] `engine/engines.py` (opt-in HEIC download, A6) (+ `test_engines.py`, 6; the real download proven once from source)
- [x] Minimal toast: `ui/toasts/model.py`, `ui/toasts/manager.py` (+ `test_toasts.py`, 15)
- [x] Fixtures and integration tests: `tests/fixtures/plugins/*`, `tests/integration/` (generated images, nothing binary checked in)
- [x] Define Compress for PNG (RD-7); validate the quality defaults (table in the report)
- [x] Add import-linter contracts R2, R3 and R4 (6 contracts kept)
- [x] **Qt-free worker executable** (`morphwheel-worker.exe` + `set_executable`): built, and `morphwheel.exe --worker-check` on the frozen build shows both workers Qt-free (A5a)
- [x] Carry-over from RF-3: `Task.source_format`, filled from the sniffed `FileInfo` (RD-9); the worker sniffs itself when it is `None`
- [x] Carry-over from RF-10: no `asdict()` on a `Task` anywhere (the pipe carries the dataclass; `__getstate__` handles the options)
- [x] Carry-over from S2: the dispatcher is connected to `Controller.drop_received`; the sniffer thread (`ui/wheel/sniffer.py`) and the second `set_plan`; `dev_catalog()` and `missing_engines={HEIC}` replaced by the manifest and the engine registry
- [x] Carry-over from S2 (security note): the drag source's integrity level is checked at the press (RD-8); outputs stay beside the source (or in `Downloads\Morphwheel`)
- [x] Carry-over from S2: `tools/drag_probe.py` honors `SM_SWAPBUTTON` in its DragLeave check (RD-5)
- [x] Sprint report: [`docs/sprints/S3.md`](sprints/S3.md)

**Exit criteria (phase-4 §9):**
- [x] Criteria 1–4 of phase 2: 1 ✅ every writing test checks the source folder (👤 C23 by hand); 2–3 unchanged since S2 (synthetic); 4 ✅ 12 MP HEIC → JPG in 0.7 s
- [x] Conversion-time target proposed: T7 (≤ 1.5 s for a 12 MP HEIC → JPG)
- [x] The "malicious" plugin test leads to an alert (`SOURCE_CHANGED`, critical, sticky toast)
- [x] Compress for PNG defined (RD-7); quality defaults validated on synthetic images
- [x] Gates green: ruff, format, mypy (47 files), import-linter (R1, P1, P2, R2, R3, R4), 604 tests; frozen build 83 MB, Defender clean, `--worker-check` OK
- [x] 👤 S3, RD-7 to RD-10 and T7 approved 2026-10-29
- [ ] 👤 By hand C23–C27 (any time before S7)

### S4: Final wheel (M2)
- [x] `ui/theme.py` (+ `tests/qt/test_theme.py`, 8: the WinUI tokens, High Contrast from the system palette, motion durations and the curve)
- [x] `ui/wheel/renderer.py` (+ `test_renderer.py`, 137: the alpha floor in 7 states × 9 frames × 2 DPRs, the look, the layer cache, paint cost)
- [x] `ui/wheel/animator.py` (+ `test_animator.py`, 18: the motion table, zero durations, the dismiss token, the real-time backstop)
- [x] `ui/wheel/window.py` (final) (+ `test_wheel_window.py`, 59: the S2 safety matrix kept; the floor at mid-appear, mid-fade and mid-shrink frames; `hide()` after every fade; the floor survives a painting failure)
- [x] Qt tests: alpha floor and hide-after-fade (above), plus two controller scenarios with motion on
- [x] M2 checks 1, 3, 6, 9: 1 ✅ offscreen (every frame of the fade); 3 ✅ synthetic since S2 (C16, C17) and the halo pixels offscreen; 6 ✅ 3.0 ms per rebuilt frame, 0.2 ms per group-fade frame at 150 % (raster only; the live number is the DEBUG line at hide, C30 👤); 9: the floor hides with the window (offscreen) and 👤 C29 by hand
- [x] M2 check 2 (DROPDESCRIPTION): feasibility only, deferred (RD-12). Qt exposes no `IDataObject`; the route is a platform-layer `IDropTarget` wrapper (see the S4 report)
- [x] Carry-over from S3: the sniffer's second `set_plan` keeps arming, hover and the bulge (`test_the_second_plan_from_the_sniff_keeps_arming_and_hover`)
- [x] RF-13 closed (RD-11): a reason-less EMPTY slot is not a hover; the hub keeps showing the files
- [x] `--motion auto|on|off` (RD-14), so the fades can be hand-tested over RDP; the controller passes the hide reason; `app` injects Windows' animation and High Contrast switches (P2 kept)
- [x] Checklist rows C28–C31; README (`--motion`)
- [x] Sprint report: [`docs/sprints/S4.md`](sprints/S4.md)

**Exit criteria (phase-4 §9):**
- [x] Every phase-3 §3 state works: rendered offscreen and inspected (waiting, armed, hover, disabled hover, not supported, More open, halo, drop flash; Light, Dark, High Contrast)
- [x] M2 checks 1, 2, 3, 6 and 9 (above; 2 deferred by RD-12; 9 and the live 60 fps number 👤)
- [x] Gates green: ruff, format, mypy (50 files), import-linter (6 contracts), 807 tests
- [x] 👤 S4 and RD-11 to RD-14 approved 2026-11-04
- [ ] 👤 By hand C28–C31 (any time before S7)

### S5: Surrounding UI (M2)
- [x] `settings/model.py` and `settings/store.py` (+ `tests/unit/test_settings_model.py`, 35; `tests/unit/test_settings_store.py`, 12; `tests/qt/test_settings_signals.py`, 5; the wiring in `application.py`, 1). RD-15: tolerant read, re-read-and-merge before every atomic save, a corrupt file moved aside, a locked file refuses the save. The app pushes the whole value through `_apply_settings` at start and on every change (the §6 D8 row: the key reaches the poller at once)
- [x] `ui/toasts/*` (+ `tests/qt/test_toasts.py`, 18; `tests/qt/test_toast_widget.py`, 14; `tests/qt/test_application.py`, +3; `tests/unit/test_shell.py`, +3; `tests/unit/test_win32.py`, +1). The buttons Show in folder, Undo / Undo all and Details as data (`ToastAction`) that the manager turns into three signals and the app wires (P2); `platform/shell.reveal_in_explorer` through a PIDL (never a command line); the single-file working toast after 1 s (`show_later`), the batch bar; the look from `ui/theme.py` (rounded translucent surface, the kind's stripe, High Contrast opaque with 2 px borders, RTL mirrored, rendered and inspected in the three schemes); rise-and-fade motion owned by the widget, positions owned by the manager; toasts held while the wheel is visible (C1, `WheelWindow.hidden` → `release`). RD-17. Details is a reusable non-modal `QMessageBox` until file 6
- [x] Carry-over from S3: a download dialog for the HEIC engine and a catalog refresh after an install, the download off the GUI thread → S5 file 6 (`--install-heic` stays for the console)
- [x] Carry-over from S4, first half: the toasts consume `ui/theme.py` (`Fonts.toast_*`, `Palette.critical/success/caution`, `current_theme` shared with the wheel)
- [ ] → S7 (moved 2026-11-12, not done in S5): Carry-over from S4, second half: the Fluent icons for Compress, PDF, More and Cancel once `qsvg` is back (today: text labels and the glyphs ⋯ ✕ ⊘)
- [x] Carry-over from S4: S/M/L only when the wheel is hidden (U4) → RD-16: `apply_size` keeps a change asked for while visible and applies it in `hideEvent`; the dialog needs no special case
- [ ] → S7 (moved 2026-11-12, not done in S5): Carry-over from S4: a `WindowTransparentForInput` experiment for the 83–250 ms fade (RD-13), hand-tested; and the `ApplicationPaletteChange` event for a live accent change (today: re-read at each show)
- [x] `ui/tray.py` (+ `tests/qt/test_tray.py`, 15; `tests/qt/test_application.py`, +1; `tests/unit/test_system.py`, +1; `tests/unit/test_shell.py`, +1). Four states by precedence (alert > working > paused > normal) with the phase-3 §6.1 tooltips; the icon painted by a `QIconEngine` at the size the shell asks for (no image-format plugin), white or near-black after Windows' mode (`platform/system.light_taskbar`, `winreg`); the working arc at 8 fps only while shown and animations are on (C7: a fixed dot otherwise); the menu asks through signals, pause is the `paused` setting round-tripped through the store; `shell.open_folder` for the log folder; `ui/text.py` holds the shared `tr` and `trigger_key_label`. Settings… and About only log until files 4 and 6. RD-18
- [x] `ui/settings_window.py` (+ `tests/qt/test_settings_window.py`, 8; `tests/qt/test_application.py`, +1). A plain focused window (not a `QDialog`): a sidebar (General, Conversion, About; Plugins arrives in S6) and a stack; every control shows the store's value and writes a change at once through `SettingsStore.update`; a slider saves once per gesture (a 300 ms debounce flushed by the release and by the hide); a refresh from another owner never overwrites an edit in progress; a failed save is said in the window's bar until the next successful save; Esc and the close button hide it; the tray brings the one window back on the page it was left. RD-19. Mica stays an open item (it only tints the title bar over an opaque client and can't be seen over RDP); the `windows11` style is Qt's default on Windows 11, so no style switch
- [x] `ui/onboarding.py` (+ `tests/qt/test_onboarding.py`, 9; `tests/qt/test_application.py`, +7; `tests/qt/test_settings_signals.py`, +3). The first-run bubble is a sticky toast in the work-area corner (RD-20): `ToastKind.HINT`, the buttons Got it and Settings, the trigger key's name in the text; scheduled 0.8 s after the start while `onboarding_done` is false; acknowledged by Got it, Settings, ✕, opening the settings from the tray, or the first drop; quitting is not an acknowledgement. The manager gained `closed(key)`, `dismiss(key)` and `settings_clicked(page)`. The store now re-reads a file it couldn't read before every write (RD-21)
- [x] `ui/dialogs.py` (+ `tests/qt/test_dialogs.py`, 4; `tests/qt/test_application.py`, +6; `tests/qt/test_settings_window.py`, +1; `tests/qt/test_wheel_window.py`, +1; `tests/unit/test_engines.py`, +1; `tests/unit/fake_heic.py` shared). The elevated warning moved out of the app (modal, before the controller starts); the Details window (a plain window: read-only text, Copy, Close; closes RD-17(g)); the tray's About opens the settings on About. The S3 carry-over: the wheel reports a drag the HEIC engine would have served, the app offers the download once per run, a non-modal consent names the wheel, the size, PyPI and the GPLv2 with Cancel as the default, the download runs on a thread the app holds, and the catalog refreshes in place (no restart: the workers find the engine by themselves); the Conversion page's HEIC row installs and removes. `EngineInstallError` carries a `kind`, the engine's only exception. RD-22
- [x] `platform/autostart.py` and `platform/single_instance.py` (+ `tests/unit/test_autostart.py`, 4, against a throwaway key; `tests/qt/test_single_instance.py`, 4, with unique names; `tests/qt/test_application.py`, +4; `tests/unit/test_win32.py`, +1). Start with Windows: the Run value is the truth at start and the setting after a change (RD-23); only the installed app reads or writes it; Task Manager's Disable is honoured and cleared on a user's "on"; the value is rewritten only when it differs. One instance per session: a fixed mutex `Local\\Morphwheel` (for the installer's `AppMutex` too), released before a restart from elevated and at every exit; a second start knocks on a per-session pipe opened for this user only and exits, and the first opens its settings. The P1 contract names three adapters now, and its warn mode is gone
- [x] `i18n/` (+ `tests/qt/test_i18n.py`, 10; `tests/qt/test_translations_tool.py`, 11; `tests/unit/test_settings_model.py`, +2; `tests/qt/test_wheel_window.py`, +1; `tests/qt/test_application.py`, +1; `tests/qt/test_toast_widget.py`, the RTL test extended; `tests/conftest.py`: a Hebrew catalog compiled once per session). One `translate` in the shape `lupdate` reads (RD-24), the toasts' shorthand inlined, the key labels as `QT_TRANSLATE_NOOP` marks; `install` loads `morphwheel_<tag>.qm` for the `language` setting or Windows' language list (stopping at English), Qt's `qtbase` catalog with it, and sets the direction explicitly; the wheel pinned left-to-right; `tools/translations.py` (`check`, `update`, `release`) with an AST guard a test holds equal to `lupdate`'s extraction (135 strings); the toast's lines align to the layout's edge (found in the Hebrew render); `*.qm` ignored, a guarded `datas` glob in the spec; `docs/translations.md`
- [x] Carry-over to S7 (installer), listed under S7: `AppMutex=Morphwheel` in `morphwheel.iss`; the autostart checkbox writes `Run\\Morphwheel` with the quoted exe path (the app adopts it at start, RD-23); the uninstaller deletes the value and may leave `settings.toml`
- [ ] → S7 (moved 2026-11-12; the tray icon needs none since file 3, it is painted by a `QIconEngine`; `qsvg` matters only with the Fluent icons): **Re-allow the Qt `imageformats` plugins the icons need** (at least `qico`, and `qsvg` for SVG icons) in the spec. The S0 trim removed them, and a `QIcon` from an `.ico` would otherwise fail silently.
- [x] M2 checks 4, 5, 7, 8: 4 the elevated restart is RD-6 and RD-22, 👤 C21; 5 Mica stays an open item (it only tints the title bar over an opaque client and can't be seen over RDP, RD-19), blur in the wheel not pursued (its surface is the alpha-1 floor, C3); 7 the toasts take no focus and their buttons are real `QPushButton`s (`test_toasts.py`, `test_toast_widget.py`), 👤 C32 and C33 across monitors; 8 the bubble is anchored to the work-area corner (RD-20), 👤 C36
- [x] Checklist row C39; `docs/translations.md`; `docs/README.md`
- [x] Sprint report: [`docs/sprints/S5.md`](sprints/S5.md)

**Exit criteria (phase-4 §9):**
- [x] M2 done: every phase-3 §6 surface is built (toasts, tray, settings, first-run bubble, dialogs, the HEIC download, autostart, one instance, i18n); the Fluent icons and the Mica tint stay open (S7)
- [x] M2 checks 4, 5, 7 and 8 (above)
- [x] The first-run flow works: offscreen (`test_onboarding.py`, `test_application.py`), 👤 C36 by hand
- [x] Gates green: ruff, format, mypy (61 files), import-linter (6 contracts), 982 tests
- [x] 👤 S5 and RD-15 to RD-24 approved 2026-11-12
- [ ] 👤 By hand C32–C39 (any time before S7)

### S6: Plugin system (M3)
- [ ] `plugins/discovery.py`
- [ ] `plugins/registry.py`
- [ ] Plugins settings page and trust dialog
- [ ] `sys.path` scoping in the loader (in place since S3: the plugin dir is appended; S6 adds the trust gate)
- [ ] `examples/sample_plugin/`
- [ ] `docs/plugins.md`
- [ ] Crash and timeout tests
- [ ] Carry-over from S5 (security note): validate `plugins.enabled` / `plugins.order` ids against the manifest id pattern before any of them maps onto `plugins_dir/<id>`; the settings parser accepts any non-blank string

### S7: Release v0.1 (M4)
- [ ] Final `morphwheel.spec`
- [ ] `packaging/inno/morphwheel.iss`
- [ ] `.github/workflows/release.yml`
- [ ] Carry-over from S5: `tools/translations.py release` before PyInstaller in the release workflow (the spec bundles `i18n/translations/*.qm` when any exists); `AppMutex=Morphwheel` and the autostart checkbox (`Run\Morphwheel`, the quoted exe path; the uninstaller deletes it) in `morphwheel.iss` (RD-23)
- [ ] Carry-over from S4 via S5: re-allow `qsvg` (and `qico` if an `.ico` is ever loaded) in the final spec, then the Fluent icons for Compress, PDF, More and Cancel (today: text labels and the glyphs ⋯ ✕ ⊘)
- [ ] Carry-over from S4 via S5: the `WindowTransparentForInput` experiment for the 83–250 ms fade (RD-13), hand-tested; the `ApplicationPaletteChange` event for a live accent change (today: re-read at each show)
- [ ] `packaging/winget/*`
- [ ] `README.md`, `PRIVACY.md`, `SECURITY.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`
- [ ] `docs/architecture.md`
- [ ] Carry-over from S3: MERGE the two PYZ archives if size matters; `--worker-check` is the release smoke test for A5a; teach `tools/wheel_driver.py` the S3 log lines so C23 can be scripted
- [ ] 👤 SignPath, publish the release, winget PR

---

## Review findings to fix (2026-10-19, a high-effort code review of all committed code)

A security review of the same scope found no HIGH or MEDIUM issues. It notes that the riskiest code
(`reserve_unique`, the worker's Pillow decode, plugin discovery and the HEIC download) doesn't exist yet,
so review it when it lands (S3, S6).

Every fix has a regression test, and each test was seen to fail on the old code first.

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| RF-1 | **High** | `packaging/pyinstaller/morphwheel.spec:58` | The spec drops **Python's own** OpenSSL (`libcrypto-3.dll`, `libssl-3.dll`). The frozen `_ssl.pyd` imports exactly those, so `import ssl` fails in the built app and breaks the HEIC download (A6). The spec keeps the unused `-3-x64` pair instead. Swap the two, rebuild, and prove `import ssl` works in the frozen app. | ✅ 2026-10-19. The `-3-x64` pair was Git's MinGW OpenSSL from PATH. The spec now drops that pair and fails the build unless Python's pair comes from the interpreter's `DLLs` folder (negative-controlled). The probe's `measure` gained a `tls` check: the frozen app loads OpenSSL 3.0.16 and 62 root certs; with `libssl-3.dll` hidden, it reports the original DLL error. |
| RF-2 | Med | `core/wheel_session.py:152` | `decide_drop()` calls `on_pointer()`, which can **open the More arc during the drop itself** and accept a plugin item the user never saw. Decide using the state before the call. | ✅ The drop uses the More state last shown. Arming still applies at the drop (RD-1, approved). |
| RF-3 | Med | `core/output_policy.py:27` | Compress takes the output extension from the file name, not the detected format. A sniffed file with no extension produces an output with no extension, and a mislabeled file keeps its wrong extension. | ✅ `candidate_paths(..., source_format=)`. The S3 carry-over adds the field to `Task`. |
| RF-4 | Med | `core/catalog.py:187` | `is` checks on StrEnum fields fail when values arrive as plain `str` (manifests, S3). Coerce or validate in `Target.__post_init__`. | ✅ Coerced, so unknown values raise `ValueError` |
| RF-5 | Med | `core/jobs.py:111` | A Compress batch where some files are "already compact" reports `PARTIAL`, which is shown as a failure. | ✅ Now `SUCCESS`, with `already_compact` listed apart from `failed` (RD-2, approved). |
| RF-6 | Low | `tools/drag_probe.py:240` | `measure()` hangs forever if a worker fails to start. Add a timeout. | ✅ A dead worker is reported in ~3 s and a hung one after 60 s, from source and frozen |
| RF-7 | Low | `tools/drag_probe.py:275` | The probe reimplements hit-testing and the gesture instead of driving core `WheelGeometry`, `GestureMachine` and `WheelSession`, so the checklist doesn't exercise the real rules (gaps, U1, U7). | S2 |
| RF-8 | Low | `tools/drag_probe.py:401` | `foreground_info()` runs between `show()` and DragEnter, which biases the latency measured in C11. | ✅ Logged on its own `FG` line, 300 ms after `SHOW`. Not yet confirmed by a real drag (👤 #3). |
| RF-9 | Low | `.github/workflows/ci.yml:16` | `cancel-in-progress` on `main` can leave a commit with no CI result. Limit it to PRs. | ✅ Only PRs share a concurrency group; every other run gets its own (`run_id`). A newer run also cancels a *pending* one, so `cancel-in-progress: false` alone wasn't enough. Confirmed only by the next push. |
| RF-10 | Low | `core/jobs.py:34` | `Task` is a frozen dataclass with a `dict` field, so `hash()` raises and the options can still be mutated. | ✅ Read-only options (copied), left out of `hash()`. Pickle and deepcopy still work. |
| RF-11 | Low | `core/catalog.py:144` | `Catalog` is mutable, so changing its targets leaves the cached slots and arc stale. | Before S6 |
| RF-12 | Low | `core/gesture.py:201` | Any event that isn't handled falls through and is treated as a `Tick`. Add an explicit branch plus `assert_never`. | ✅ |
| RF-13 | Low | `core/wheel_session.py:261` | Hovering an EMPTY slot gives a DISABLED hub with `reason=None`. | ✅ S4 (RD-11): a reason-less EMPTY slot is not a hover; the hub keeps the files line. More without plugins keeps its reason |
| RF-14 | Low | `core/formats.py:129` | BMP is detected from `"BM"` alone, so non-images that start with `BM` are reclassified as BMP. | ✅ Also needs a DIB header size Pillow accepts (12–124) |
| RF-15 | Low | `packaging/pyinstaller/file_version_info.txt:26` | The version resource says `OriginalFilename=morphwheel.exe` but is attached to `drag_probe.exe`. | ✅ S3: the spec builds `morphwheel.exe` (and `morphwheel-worker.exe`); the probe is no longer frozen |

A code review of the fixes found 8 more issues. 5 are fixed, including a name like `Dr. Who`, which lost ` Who`, and a guard compare that didn't resolve paths. The other 3 became RD-1 and the S3 carry-overs above.

**Decisions from the RF fixes:** RD-1 (a drop still counts toward arming; the More arc is frozen), RD-2 ("already compact" is not a failure) and RD-3 (names cut only a known image extension). ✅ Approved by Yuval 2026-10-19 and recorded in [`decisions.md`](decisions.md).

## Pending actions for Yuval 👤

| # | Action | Needed by |
|---|---|---|
| 1 | ~~Create the GitHub org `morphwheel` and a public repo~~ ✅ 2026-10-19: Yuval created the org; the public repo [MorphWheel/morphwheel](https://github.com/MorphWheel/morphwheel) was created, with private vulnerability reporting on | Done |
| 1b | ~~First commit and push~~ ✅ pushed to `main` at Yuval's request. Recommended: require 2FA for org members (Org settings → Authentication security) | Done (2FA: Yuval) |
| 2 | Apply to SignPath Foundation | Before S7 (S0-3) |
| 3 | Run the manual drag checklist rows C4, C9 and C11 by hand (C11 at the physical machine). The synthetic passes close the other rows (S0-3) | Before S7 (S0-3) |
| 6 | By hand, any time before S7: C21 (start the app from an administrator terminal, click *Restart normally*) and C22 (swapped mouse buttons) | Before S7 |
| 7 | ~~Approve S3~~ ✅ 2026-10-29: S3, RD-7 to RD-10 and T7 approved; committed to `main` | Done |
| 8 | By hand, any time before S7: C23 (a real conversion), C24 (mixed drag), C25 (already compact), C26 (read-only folder), C27 (HEIC with `--install-heic`). The download sends nothing but a request to PyPI's file host | Before S7 |
| 9 | Optional: upload `morphwheel-worker.exe` (new in S3) to VirusTotal, like the S0 build (this sends the file to a third party) | Any time |
| 10 | ~~Approve S4~~ ✅ 2026-11-04: S4 and RD-11 to RD-14 approved; committed and pushed to `main` at Yuval's request, CI green | Done |
| 12 | ~~Approve S5 with RD-15 to RD-24~~ ✅ 2026-11-12. By hand, any time before S7: C32–C39 (C37 and C38 on the frozen build; C39 needs a compiled Hebrew catalog) | Before S7 |
| 11 | By hand, any time before S7: C28 (drop during the appear animation), C29 (nothing catches after the fade), C30 (motion and look, on a local console), C31 (High Contrast and a scheme switch). C28 and C29 need `--motion on` over RDP | Before S7 |
| 4 | Optional: upload the build to VirusTotal (this sends the file to a third party) | End of S0 |
| 5 | Decide whether to delete the temporary spike venv (`%LOCALAPPDATA%\Temp\twspk`, ~280 MB). Nothing uses it. | Any time |

## Open items to verify 🔶

| Item | Sprint |
|---|---|
| ~~`import ssl` works in the frozen app after the RF-1 fix~~ ✅ OpenSSL 3.0.16, 62 root certs, no network used. ~~A real HTTPS download is still unproven (S3, A6).~~ ✅ proven from source in S3 | S0 |
| ~~Worker cold start when frozen; `freeze_support` together with spawn~~ ✅ 0.17–0.20 s, works | S0 |
| ~~Separate Qt-free worker exe through `multiprocessing.set_executable`~~ ✅ built and proven by `--worker-check` on the frozen build (A5a) | S3 |
| ~~Memory use of the GUI plus 2 workers~~ ✅ 57 + 2×38.5 MB working set, frozen | S0 |
| Loading the pillow-heif `cp312` wheel from inside the frozen app (A6): ✅ from source (the download, the hash, the flat install and a 12 MP decode from an isolated interpreter). From the *frozen* worker: still unverified. S5 file 6 gives the in-app install; 👤 C37 on the frozen build proves it | S0/S3 → S5 👤 |
| ~~"Restart normally" from an elevated window~~ implemented (RD-6); 👤 C21 proves it | S2 |
| ~~Per-element fade with no drop-transparent gap~~ ✅ S4: one content layer faded as a group over an unscaled alpha-1 floor, clipped to the halo. Proven offscreen in every state and frame (renderer: 126 combinations; window: mid-appear, mid-fade, mid-shrink; a 1 818-frame spike scanned every pixel). 👤 C28 by hand | S4 |
| DROPDESCRIPTION, to show "Convert to JPG" instead of "Copy": **deferred** (RD-12). Qt gives the widget no `IDataObject`; the route is a ctypes `IDropTarget` wrapper around Qt's (OLE keeps it in the `OleDropTargetInterface` window property) that calls `IDataObject::SetData(CFSTR_DROPDESCRIPTION)` on DragEnter; platform-layer work plus a hand-tested drag | post-MVP |
| The fading wheel keeps catching input for 83 ms (250 ms after a drop): a press there is swallowed, a re-entered drag gets "no drop" (RD-13). `WindowTransparentForInput` would need a hand-tested drag (changing flags on a shown window re-creates it) | S7 👤 |
| `tests/qt/test_application.py` prints three "access violation" messages at teardown (present before S4, the tests pass). Narrowed in S5 file 2: all three come from the worker pool's `_spawn` (`multiprocessing` `CreateProcess` on the supervisor thread), none from the toasts. Not isolated further | S5 |
| Mica in the settings window (RD-19: it only tints the title bar over an opaque client, invisible over RDP); blur in the wheel not pursued (its surface is the alpha-1 floor) | post-MVP |
| ~~Placing the onboarding bubble when the tray icon is in the overflow area~~ ✅ S5 file 5: the bubble is anchored to the work-area corner, as phase-3 §6.3 rules, and never points at the icon (RD-20). 👤 C36 by hand. On a right-to-left Windows the tray is bottom-left while the toast stack stays bottom-right: for the Hebrew work (D3a) | S5 |
| A settings file that was unreadable at the start is read again only at the next write (RD-21): until then the session runs on the defaults (trigger key, sizes, qualities). A retry on a timer that tells the owners when the file reads would close that; a behaviour decision, not made here | 👤 |
| The tray icon's ink follows Windows' mode (`SystemUsesLightTheme`), re-read on a state change and on Qt's `colorSchemeChanged`, which Windows raises for the *app* mode. A switch of the taskbar mode alone repaints only at the next state change. The mechanism-level fix is a `WM_SETTINGCHANGE` (`ImmersiveColorSet`) listener in `platform/`; cosmetic, so deferred | post-MVP |
| Two full-suite runs timed out (> 3 min) inside `tests/qt/test_controller.py::test_with_motion_on_a_drop_flashes_then_fades_and_hides` on 2026-11-04, while a stuck pytest process from an earlier run (a `mkstemp` loop in a locked folder, since replaced) was spinning at 100 % of a core. Five later runs passed in 14 s. Not reproduced, not explained | S5 |

## Work log (newest first)

- **2026-11-12**: Yuval approved S5 with RD-15 to RD-24 (A2). Committed and pushed to main at Yuval request (bbde8b7). CI failed once: test_autostart expected a quoted exe path, and the runner path has no space, so the Run value is unquoted there; the test now compares against list2cmdline (710b93c), CI green.
- **2026-11-12 (S5 file 8, S5 closed)**
  - Plan from the one phase-4 line, D3/D3a and phase-3 §6.2, spiked first: Qt's `lupdate` read our `tr("Tray", "text")` as the source "Tray" with the text as a comment and never saw the toasts' `_tr` (36 of 115 strings, all wrong), so the helper took Qt's own name and shape. The plan review found four blocking items: `QTranslator.load(QLocale.system(), …)` walks every language Windows lists (this machine would have picked a Hebrew catalog the day one ships), a default-argument seam that can't be patched, the key-label lookup tripping the guard, and the guard missing `QT_TRANSLATE_NOOP` and the class context of `self.tr`. All folded in before code.
  - UI pass: a toast rendered with a compiled Hebrew catalog on the Windows platform (offscreen has no fonts). One real finding: a Latin file name sat left-aligned with its indent on the wrong side under a right-aligned Hebrew title, because `QLabel` aligns "leading" by each line's own script; the toast now aligns to the layout's edge absolutely (`test_rtl_mirrors_the_layout` extended). Qt's Cancel and OK came along from `qtbase_he`.
  - My code review: 5 items, all fixed (the alignment above, a dead fallback, a test-only parameter, the catalog compiled per test, the nested callee match). The security review found nothing above its bar. Four cleanup lenses: 17 of 19 applied (a session-compiled Hebrew catalog in `conftest.py`, the catalog name shared with the tool, one tool runner, a flat `match` on the callee, a dataclass, the guard refusing any `*.translate` with a literal, `SimpleNamespace` stubs, fewer duplicated asserts); skipped one `setLayoutDirection` call (the early return reads better) and the English plural-only catalog (the root-cause option; RD-24 records it as the alternative not taken: a user decision). The access-violation dumps are the known open item (the pool's `_spawn`), unchanged.
  - Sprint close: M2 checks 4, 5, 7, 8 mapped; the Fluent icons, the `imageformats` plugins and the `WindowTransparentForInput` experiment moved to S7; `docs/sprints/S5.md` written. Gates: ruff, format, mypy (61 files), import-linter (6 contracts), 982 tests (25 new), three consecutive runs. Nothing committed; waiting for the S5 approval (A2).
- **2026-11-10 (S5 file 7)**
  - Plan from phase-4 §2/§5/§10 and phase-2 §3.7, spiked first (the mutex twice in one process, the pipe knock without an event loop, the registry round trip on a throwaway key), then reviewed before any code. Five blocking findings shaped it: the registry is adopted at start instead of overwritten (the installer's checkbox would have been deleted on the first run), the mutex is released before a restart from elevated and on every early exit (the restarted instance could have found the name held and both could have exited), tests can never reach the real Run key or the real pipe (two app tests built `Application` directly), the connection itself is the message (the payload isn't there yet when the connection arrives), and a refused mutex handle is closed (or the name lives on). Also from the review: a fixed mutex name for the installer, the session id in the pipe name only, no stale-pipe cleanup (a no-op on Windows), Task Manager's Disable honoured, no console-window command line from source.
  - My code review found 2 items, both fixed: from source the app would still have deleted an installed Morphwheel's Run value on the developer's machine, and the registry adoption would have flipped a toggle set from source back to off; from source the registry is now neither read as the truth nor written. The security review found one real item, fixed: Windows' default named-pipe security would have let any local account knock, so the pipe is opened for this user only; its functional note was taken too: an "off" adopted at start writes nothing, so Task Manager's Disable stays reversible. Four cleanup lenses: 13 of 15 applied (one registry-read helper, the dead constructor seams out, a shared unique-names fixture, the app factory forwarding overrides, the accepted connection closed at once, which also removed a five-second wait from one test, the registry written only when the value differs, the second-start test on the contract, the import-linter warn mode retired); skipped a private call in one test and a test's `start()`.
  - No visible UI in this file. Checklist row C38 for the hand checks (the Run value, a sign-in, Task Manager, a second start, a second session, the elevated restart).
  - Gates: ruff, format, mypy (60 files), import-linter (6 contracts, three adapters), 956 tests (13 new). Nothing committed.
- **2026-11-10 (S5 file 6)**
  - Plan from phase-3 §6.4/§6.5, phase-4's A6 notes and the S3 carry-over, reviewed before any code (threads and Qt, the project's UX rules, the download consent). Five blocking findings shaped it: the app holds the download job until its result is handled (a job held only by its thread is freed with it, and a freed sender's queued signal never arrives: verified), the thread never raises on a dead signal at shutdown, the offer toast gets the size from the app (the ui layer may not import the engine module), failure texts are translated lines keyed by the engine's failure kind, and the catalog swaps at once with the docstring saying so. Also from the review: the engine-missing signal fires where the plan is computed, a third "installing" state on the settings row, Cancel as the consent's default (the §6.5 precedent), no consent for removal, no format id threaded through, and the dispatcher setter dropped as dead API.
  - A code review (high) found 2 items, both fixed (a consent asked again after the engine was installed by another path; the removal's files-in-use branch untested). The security review found nothing above its bar (the consent gate, the pinned hash on the same bytes that are unpacked, the install path, the test-only fetch seam, the thread handoff and the plain-text widgets all checked). Four cleanup lenses: 12 of 14 applied (one exception contract in the engine, with `write` as the fourth kind, so the thread, the toast mapping and the console path read the same thing; removal reports its own outcome; one helper pushes the settings row's state; the consent box exposes its buttons; the shared alias, the wheel-spec pin and the Details title deduplicated; the window test renamed to what it proves); skipped an Esc shortcut helper and dropping the settings window's `open_and_raise`.
  - UI pass: the Details window, the consent box, the elevated box and the five HEIC toasts rendered offscreen, LTR and RTL, and inspected. Checklist row C37 for the hand checks on the frozen build, which is also where the frozen worker's load of the downloaded engine (the S0/S3 open item) gets its proof.
  - Gates: ruff, format, mypy (58 files), import-linter (6 contracts), 943 tests (12 new). Nothing committed.
- **2026-11-05 (S5 file 5)**
  - Plan from phase-3 §6.3, reviewed before any code (state and lifecycle, the project's rules). The review found a real bug in the plan: re-wording the bubble on every settings change would bring it back right after the first drop whenever animations are on (the settings write lands while the bubble fades and the wheel still holds new toasts). The simpler design it suggested replaced the re-wording: opening the settings acknowledges the bubble, so the key can't go stale. Also from the review: the drop is submitted before any settings write, `closed` is emitted last and only for keyed toasts, the decision is on record (RD-20, which widens RD-17(c) by one case).
  - The review also surfaced a data hazard in the store from file 1: after a load that couldn't read the file, the first write merged the stand-in defaults over the user's real values. Fixed (RD-21) in three steps, each found by a different pass: re-read before the write (the plan review), keep the changes made while unreadable and apply them all on top of the file (my code review: a second change was resetting the first), and never take the no-op shortcut right after a re-read (the security review, confirmed against a real file lock: the store, the owners and the file could part ways).
  - A code review (high) found 3 items, all fixed (the two store items above and a list changed while it was walked in `dismiss`). The security review found the one low-severity store item above and nothing else. Four cleanup lenses: 11 of 15 applied (one resolve-then-replace flow in the store with a single piece of unread state, the acknowledgement saved before the dismiss so it doesn't re-enter itself, shared `unreadable` and `refused_saves` fixtures, an app factory fixture that always tears down, a wait on the condition instead of a fixed sleep); skipped moving the generic manager tests, a kind-to-signal table, keying the held list, and a retry timer in the store (an open item for a decision).
  - UI pass: the bubble rendered offscreen in Dark, Light and High Contrast, LTR and RTL, and inspected. Checklist row C36 for the hand checks, including the real first drag with the bubble up and the glyph's rendering.
  - Gates: ruff, format, mypy (57 files), import-linter (6 contracts), 931 tests (19 new). Nothing committed.
- **2026-11-04 (S5 file 4)**
  - Plan from phase-3 §6.2 and §6.1, phase-4 §4.6 and the §6 D8/U4 rows, reviewed before any code (binding loops, write storms, the project's rules). Five blocking findings shaped it: a debounce timer per slider row instead of commit-on-every-step (key auto-repeat and the wheel would have written the file thirty times a second), no refresh over an edit in progress (a typed value was being replaced under the user's fingers), a save error consumed by the `changed` that follows it and cleared by the next success, bound-method slots with a small slider-row widget instead of lambdas, and a loading flag that keeps the value labels in step. Also from the review: a plain window instead of a `QDialog` (Enter in a spin box would click a default button), user-only control signals (`activated`, `buttonClicked`, `clicked`), no app-wide style switch (a no-op in production, a leak across tests), a guard that never opens the window while the wheel is up (C1), Mica left out.
  - A code review (high) found 4 items, all fixed (the save error marked as one, no refresh while hidden with a catch-up on show, two slider slots instead of five, Esc tested with the focus inside a control). The security review found nothing above its bar. Four cleanup lenses: 9 of 12 applied (no dead loading flags, a signal blocker in the slider row, one page table, one loop for the quality rows, the tray connected straight to `show_settings`, the failing-save test on `monkeypatch`, a shared `rtl` fixture); skipped a spin-row helper (one spin box), a shared bring-back helper (file 6's call) and a `%1` substitution helper (codebase-wide, not this sprint). One judgement call from the lenses: a plain tray request reopens the window on the page it was left on; the bubble can still ask for a page.
  - UI pass: the three pages rendered offscreen, LTR and RTL, with the problems bar, and inspected. Checklist row C35 for the hand checks.
  - Gates: ruff, format, mypy (56 files), import-linter (6 contracts), 912 tests (9 new). Nothing committed.
- **2026-11-04 (S5 file 3)**
  - Plan from phase-3 §6.1 and §8, phase-2 §3.7 and the §6 pause row, reviewed before any code (Qt tray pitfalls, feedback loops, the project's rules). Three blocking findings shaped it: the tray is built before the settings are pushed, one `_refresh` owns the timer (it runs only while the effective state is working, the icon is shown and animations are on; a progress tick never restarts it), and every slot is a bound method or a signal. Also from the review: always `show()` (Qt re-adds the icon when Explorer restarts), a left click only (Windows sends Trigger before DoubleClick), a `QIconEngine` instead of five pixmaps (at 125 % the 20 px and 24 px pixmaps were never used), the colour-scheme hook, the menu kept as an attribute (`setContextMenu` doesn't own it). The spec gap "which problems light the dot" is RD-18 (critical results only).
  - A code review (high) found 7 items: 5 fixed (the registry read moved off the animation tick, an unchanged icon is never re-set, the registry value's type is checked, two test tidy-ups), 2 skipped with reasons (stale numbers while two jobs overlap, which self-heal at the next tick; RD-18 recorded instead). The security review found nothing above its bar. Four cleanup lenses: 14 of 16 applied (the shared `tr` in the app, the visible flag read from Qt, cached switches and ink constants, a tooltip guard, the alert fed from the toast model's Details payload, `trigger_key_label` shared for file 4, an `opened_folders` fixture); skipped the alert colour constant and the taskbar-mode listener (an open item).
  - UI pass: every state and all eight working frames rendered at 16, 24 and 32 px on a dark and a light taskbar and inspected. Checklist row C34 for the hand checks.
  - Gates: ruff, format, mypy (55 files), import-linter (6 contracts), 903 tests (18 new). Nothing committed.
- **2026-11-04 (S5 file 2)**
  - Plan from phase-3 §3, §5, §7, §8 and phase-4 §4.3, reviewed before any code from three lenses (focus stealing, data loss, stale timers). Six blocking findings shaped the design: no application-modal Details box (it would block every toast button and make the wheel refuse drags), nothing shows while the wheel is visible (C1), the manager owns the positions and the widget animates only a scalar rise, a dismissed working toast stays dismissed, the animations are widget-owned attributes (a local one would be collected mid-fade and leave a ghost), and Undo only where outputs exist. Also from the review: the ctypes return types for the PIDL calls, the COM apartment rule, no indeterminate bar.
  - A crash found by the full suite and bisected: a `QTimer` child whose lambda slot captured the manager held the manager's last reference, so the child's deferred delete freed the parent mid-destruction (abort). Fixed by bound-method slots only; the rule is in `manager.py`'s docstring and `widget.py`.
  - A code review (high) found 8 items: 6 fixed (the relayout screen after a dismiss, one reusable Details box, one job record, dead lines, two test gaps including a real MTA-thread test for the COM branch), 2 skipped with reasons (the synchronous Explorer call; RD-17 recorded instead). The security review found nothing above its bar; its robustness note (a COM failure escaping from a button slot) applied. Four cleanup lenses: 18 of 21 findings applied (the `timed` helper, one `render_widget` test helper, one easing constant, event-driven hold release through `WheelWindow.hidden`, relayout only when a toast's size changes, the smaller tidy-ups); skipped the typed-signal fan-out (a design choice), key-tagged timers, and removing the COM branch.
  - UI pass: every kind rendered offscreen in Dark, Light and High Contrast, LTR and RTL, and inspected; motion off proven by tests (instant, text instead of the bar). Checklist rows C32 and C33 for the hand checks (M2 #7; the real reveal and the real Recycle Bin).
  - Gates: ruff, format, mypy (53 files), import-linter (6 contracts), 885 tests (25 new). Nothing committed.
- **2026-11-04 (S5 file 1)**
  - Plan written from phase-4 §4.6, §5 and §6 (the D8 row), then reviewed from a data-loss lens before any code. The review's blocking finding shaped the store: a settings file that can't be read at startup must never be overwritten by the next save, so every save re-reads the file and merges into it, and refuses when that read fails (RD-15). Also from the review: a newer `schema` is never downgraded, `os.replace` retries a sharing violation, the merge recurses only into tables, the enums are case-normalized, and the pending wheel size is never dropped.
  - `settings/model.py` (frozen dataclasses with the §4.6 defaults; a tolerant parser that reports each fallback as a problem line; `asdict` as the TOML document) and `settings/store.py` (pure load/save plus a thin `SettingsStore(QObject)` with `changed` and `save_failed`). Found while testing: `tempfile.mkstemp` loops on `PermissionError` on Windows (it reads it as a name clash) and hung the suite in a locked folder; replaced by one exclusive `os.open` with a random name.
  - Wired into `application.py`: `_apply_settings` pushes the whole value to the controller (trigger key, paused), the dispatcher (converter options) and the window (size) at start and on every change; `Controller.pause`/`resume` are idempotent for it. RD-16: `WheelWindow.apply_size` defers a change made while visible to `hideEvent` instead of raising.
  - A code review (high effort) found 5 items; 4 fixed (a UTF-8 BOM read as corruption, a duplicate result type, a comment that would have routed English log lines into the UI (D3a), an untested save-path move-aside), 1 skipped (a two-line test helper duplicated, later shared through a `temp_files` fixture anyway). The security review found nothing above its bar; its note on plugin ids is an S6 carry-over. Four cleanup lenses: applied the window-owned deferral, one `_apply_settings` path, `asdict`, the single-attempt temp name, the shared test helper and a `save_settings`-built fixture; skipped the layer-forced duplicates (the `PermissionError` retry idiom and `strerror or str(e)`, which `settings` can't import from `engine`) and the two accessor properties (`Controller.trigger_key`, `JobDispatcher.options`), kept as test seams.
  - Gates green: ruff, format, mypy (52 files), import-linter (6 contracts), 860 tests (53 new). Nothing committed.

- **2026-11-02 (S4 built)**
  - Plan written from phase-3 §2, §3, §7, §8 and phase-4 §4.6/§6/§9, then attacked from two lenses before any code. The drop-safety lens found no way to accept Move or fall through, and hardened the fade: the floor painted before anything is computed, a dismiss token so a stale fade can't hide a newer wheel, a real-time backstop, `windowOpacity()` asserted mid-fade. The Qt lens changed the design: one cached content layer faded as a group (no per-primitive double blending), everything after the floor clipped to the halo, timers injectable (orphan timers under a fake clock crash the suite), the last view frozen during the fade, hover keyed on `highlight_slot`, and "Segoe UI Variable" first (the "…Text" family resolves to Bold).
  - A spike scanned every pixel of 1 818 frames (101 opacities × 3 scales × 3 DPRs × 2 formats, antialiased fills, a scaled edge line and text over an alpha-1 floor): worst alpha inside the halo 1, outside always 0.
  - Files 1–4 in the §9 order, each with its tests; the controller passes the hide reason; `app` injects the animation and High Contrast switches and the `--motion` flag; RF-13 closed in core. 807 tests (203 new).
  - A code review (high effort) found 7 items; 6 fixed (English plurals in the hub, a test for the floor under a painting failure, a frozen-view test that hid at opacity 0, content rebuilt per paint, the frame timer woken on every hover, a test-only wrapper), 1 skipped (shared pixel helpers across two suites). Four cleanup lenses (reuse, simplification, efficiency, altitude): the animator now owns the flash and the arc (no window-side animation state), the window has no frame copy and no content cache, the layer buffer is reused, fonts are built once, the floor path is cached, `Accept` carries the dropped slot, the tests share one fake clock and the session builders. Skipped with reasons: a shared High Contrast palette fixture (6 lines), inlining `Motion.ms`, dropping the defensive guard in the fade handler. The security review was not run: S4 adds no I/O, subprocess, download, plugin or ctypes surface.
  - UI pass: every phase-3 §3 state rendered to PNG and inspected in Light, Dark and High Contrast; one fix (the hub was tinted in the waiting state because the pointer sits at the center; the tint now belongs to the Cancel state only). Zero durations with animations off, High Contrast opaque with 2 px borders, strings through `tr()`, the wheel unmirrored (D3a).
  - Docs: S4 report, RD-11 to RD-14 proposed, checklist rows C28–C31 (with the `--motion on` note for RDP), README. Stopped for approval (A2); nothing committed.
- **2026-11-04**: Yuval approved S4 with RD-11 to RD-14 (A2). Committed and pushed to `main` at Yuval's request (`4de616f`); CI green in 1m32s.

- **2026-10-29 (S3 built)**
  - Plan written from phase-4 §4.4, §4.5 and §9, then attacked from two lenses before any code. The data-loss lens found two blocking holes in the §4.4 sketch (a killed worker leaving an empty `photo.jpg`; a 0-byte placeholder that isn't provably ours), fixed by delete-on-close placeholders and rename-only commits (RD-10). The process lens settled `set_executable` for a frozen child, the pool's wait on pipe plus sentinel, and the HEIC wheel's flat DLL layout.
  - Files 1–13 in the §9 order, each with its tests; then the toasts, the sniffer, the application wiring, the integrity gate (RD-8), the probe's swapped-button fix, contracts R2–R4, and the two-executable spec. 604 tests (182 new; 92 integration tests with real files and real worker processes).
  - The frozen build (83 MB) passes `--worker-check`: both workers run `morphwheel-worker.exe` with no Qt (A5a). Defender clean. Both exes carry `longPathAware`.
  - A6 proven from source: the pinned wheel downloaded (6.6 MB, 1.2 s), hash matched, installed flat; a 12 MP HEIC decoded to JPG in 0.7 s from an isolated interpreter.
  - Quality defaults measured (PSNR and size at each default and its neighbours) and Compress for PNG defined (RD-7). Conversion-time target proposed (T7).
  - A code review (high effort) on the working tree found 8 items, all fixed (a stat on the GUI thread in DragEnter, a leak for all-skipped jobs, queued tasks running after shutdown, tasks hanging when no worker starts, a stuck job when the pool refuses, dead code, a clumsy helper, a duplicated fixture). The security review found nothing above its bar; three hardening notes applied (plain-text toast labels, the file id in Undo, the engine folder appended to `sys.path`). Four cleanup lenses: 26 of 30 findings applied, 4 skipped with reasons. The frozen build was rebuilt from the final sources and re-checked.
  - Docs: S3 report, decisions RD-7 to RD-10 and T7, checklist rows C23–C27 and automated checks A4–A5, README (`--install-heic`), overview.
  - Yuval approved S3 with RD-7 to RD-10 and T7 (A2). Committed and pushed to `main` at Yuval's request; CI green on `01f4850`.

- **2026-10-29 (S0 closed, S2 started)**
  - Yuval lifted the S0-1 gate and closed S0 (S0-3). C4, C9, C11 and SignPath stay 👤 and gate S7.
  - S2 plan written and reviewed (Win32 lens, timing and state lens). Struct sizes checked against the SDK in a spike.
  - Review outcomes that shape S2: elevation is judged by the token's elevation *type* (UAC-off machines would otherwise loop through "Restart normally"); raw input and key state report *physical* buttons, so swapped buttons are handled through `SM_SWAPBUTTON`; the poller emits a `sampled` tick so the session's dwell, spinner and give-up timers advance while the pointer is still; drop/leave signals are queued so nothing heavy runs inside OLE's Drop.
  - `platform/_win32.py` + 19 layout and marshalling tests. Contracts P1 (platform Qt-free except the two adapters) and P2 (ui has no Win32). Gates green, 323 tests.
  - `platform/system.py` + 13 tests: elevation type, `restart_unelevated` (shell token → `CreateProcessWithTokenW`; the real click is a checklist row), per-DPI drag threshold with monitor and system fallbacks, swapped-button-aware `primary_button_down`, animation and High Contrast switches. 336 tests.
  - `platform/window_probe.py` + 13 tests: the allow/deny table over class chains (rejected classes win), the chain walk proven on windows the test creates. 349 tests.
  - `platform/raw_input.py` + 17 tests: `parse_raw_mouse` table (coalesced edges, swapped buttons, wheel, non-mouse), the filter logs once and never raises, `start()` reports instead of raising offscreen, `RIDEV_REMOVE` on stop. 366 tests.
  - `platform/modifier_poller.py` + 14 tests: key table (inclusive keys), edges only, reset on start, `set_key` at the next sample, Esc edges, a `sampled(t_ns)` tick, the real timer fires. The timer test caught a real bug: `Signal(int)` is a 32-bit C int, so the tick carries a Python object. 380 tests.
  - `ui/wheel/window.py` + 23 tests: the safety matrix at window level (DragEnter always Copy, DragMove/Drop only on selectable slots, never Move, a Move-only source refused at the door and in the handler, events without a session rejected), the alpha floor rendered to an image in five states (every catching pixel ≥ 1, outside 0), give-up once per session, size change only while hidden, no tooltips in the package. Finding: Qt routes a Drop only after an accepted DragEnter, which is one more reason DragEnter is always accepted. 403 tests.
  - `app/controller.py` + 11 scenarios with a fake monitor, the real poller and the real window: C1 end to end with a logged `DropRequest`, release grace, release over the hub, leaving the halo and reopening, a rejected drop, give-up, disallowed sources and our own window, pause, the trigger key, stop, reset on a new press. 414 tests.
  - `app/application.py` + 6 tests: argparse, the dev catalog (seven slots, HEIC blocked until its engine), the elevated gate with Restart normally / Quit and an explanation when the restart fails. Smoke run from source: boots, raw input registers.
  - A code review (high effort) found 10 items; 9 fixed, 1 skipped (the dev catalog duplicates the test builders until S3's manifest replaces both). The real bug: a key held across two gestures never reopened the wheel, because the poller wasn't reset on a press during the release grace. The restart now loads the token's profile and environment. A security review of the ctypes and process-creation surface found nothing above its bar (the restart is a privilege drop; no dropped path is opened in S2); its note on lower-integrity drag sources is an S3 carry-over.
  - Checklist rows C13–C22 added for the dev wheel. S2 report written. 422 tests.
  - **Scripted drags against the app** (`tools/wheel_driver.py`, reusing `drag_driver.py`; two debug log lines added to the app for state changes and hover changes): C13–C20 pass in one clean run, files unchanged. Wheel shown 1.9–8.1 ms after Shift, DragEnter 10–15 ms after shown, the drop handler 0.5–0.6 ms. Esc arrives as a DragLeave with the button down (`left_halo`).
  - Yuval approved S2 (A2). Committed and pushed to `main` at Yuval's request.

- **2026-10-26 to 2026-10-28 (scripted drag run, S0-2)**
  - Built `tools/drag_driver.py` (SendInput, ctypes only) and `tools/uia_helper.ps1` (UI Automation, read-only). Approved as S0-2: synthetic results, marked as such.
  - **Result:** C8, C1, C2, C3, C5, C7, C6 and C12 pass in one clean run (2026-10-28), files unchanged. Details in `docs/testing/integration-checklist.md`.
  - **Not covered:** C4 (UI Automation exposes no desktop icons here), C9 (UAC), C11 (physical console); C10 n/a.
  - **Found on the way:** over RDP the client echoes earlier cursor positions back after injected moves, and a press on an item's padding starts a rubber band, not a drag. The driver verifies every press and release point, and cancels with Esc when it can't.
  - 2026-10-28: committed and pushed to `main` at Yuval's request.

- **2026-10-19 (review fixes)**
  - Fixed RF-1–6, 8–10, 12 and 14. Each fix got a regression test that failed on the old code first.
  - Gates green: ruff, format, mypy, import-linter, 304 tests (27 new).
  - **Frozen rebuild:**
    - 81 MB; GUI idle 57.3 MB; workers 38.6–38.8 MB; cold start 0.16–0.17 s. In line with S0.
    - The `tls` check passes. Defender found no threats.
  - **Still open:**
    - RF-8 is unconfirmed by a real drag.
    - RF-9 is unconfirmed until the next push.
  - Yuval approved RD-1 to RD-3, recorded in `decisions.md` and cited in the code.
  - 2026-10-22: committed in three commits (probe and packaging, core, CI and docs) and pushed to `main` at Yuval's request.

- **2026-10-19 (session wrap)**
  - Gates green: ruff, format, mypy, import-linter, 277 tests. CI green on the initial commit.
  - A high-effort code review of all committed code found 15 issues, filed as RF-1 to RF-15. RF-1 is a must-fix packaging bug.
  - A security review of the same scope found nothing at HIGH or MEDIUM.
  - **Next:** fix the RF findings, then S2, once Yuval's checklist (C1–C12) and SignPath items are done.

- **2026-10-19 (history cleanup)**
  - The initial commit was rewritten and force-pushed; CI is ✅ green on it.
  - Local-only working files are now excluded from the repository.

- **2026-10-19 (repo live)**
  - Yuval created the GitHub org `MorphWheel`.
  - The public repo `MorphWheel/morphwheel` was created, with private vulnerability reporting enabled.
  - `git init`, then the first commit, pushed to `main`.
  - The first CI run is ✅ green: ruff, format, mypy, import-linter, 277 tests.
  - Still open before S2: checklist C1–C12 (👤) and the SignPath application (👤).

- **2026-10-19 (S1 approved)**
  - Yuval approved S1 and is doing the S0 items.
  - **A1 reconfirmed:** a GitHub org `morphwheel` with a public repo `morphwheel/morphwheel`. Yuval is creating it.

- **2026-10-19 (S1 complete)**
  - **Files:** all 8 core files written, with tests. 277 tests pass; mypy strict, ruff and import-linter R1 are green.
  - **Review fixes:** a stale trigger-key state between gestures, and a missing give-up exit.
  - **Behavior:** gesture release ordering is handled by a `RELEASING` state.
  - **Probe fix:** the drag probe no longer hides on the raw mouse-up, so drops aren't lost. The frozen probe was rebuilt.
  - **Now:** waiting for approval of S1. S2 is blocked on S0's 👤 items.

- **2026-10-19 (S1 started)**
  - Yuval approved: start S1 now with S0's 👤 items closing before S2 (S0-1); targets T5/T6; a Qt-free worker exe in S3 (A5a).

- **2026-10-19 (S0 code complete)**
  - **Files:** S0 files 6–11 written. All local gates are green.
  - **Measurements:** frozen build is 82 MB after trimming about 30 MB; worker cold start 0.17–0.20 s; GUI idle 57 MB.
  - **Defender:** no threats.
  - **Findings:**
    - Frozen workers load QtCore through PyInstaller's runtime hook. Fix planned in S3: a separate worker exe.
    - No license texts are bundled yet. Planned for S7.
  - **Now:** waiting for approval of S0 plus 👤 actions.

- **2026-10-19:**
  - **Decisions**
    - Discovery phases 1–4 and the spike were approved, and Phase 5 started.
    - Yuval kept the name **Morphwheel** (D6).
    - The app is English-native, and **Hebrew is the first language added** (D3a).
    - **Docs and chat switched to English** (L1).
  - **Docs and tracking**
    - Yuval asked for in-repo docs and progress tracking. Created `docs/README.md`, `overview.md`, `decisions.md` and `progress.md`.
  - **S0 progress**
    - Created `.venv` with the pinned dependencies.
    - Wrote S0 files 1–5. Paths resolve to `%APPDATA%\Morphwheel` and `%LOCALAPPDATA%\Morphwheel`.
    - Verified that Qt proposes **Move** under Shift on both the `offscreen` and `windows` platforms. This is the hazard `force_copy` blocks.
