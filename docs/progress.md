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
| **Sprint** | S3 ✅ approved 2026-10-29 (M1 complete). **S4 is next** (M2: the final wheel). S0 closed (S0-3), S1 ✅, S2 ✅ |
| **Current task** | S3 approved and committed to `main` on 2026-10-29. Next: S4 file 1, `ui/theme.py` |
| **Next** | S4 (the final wheel). Carry-overs listed under S4 and S5. RF-7 and RF-11/13 still open |
| **Blocked on** | Nothing. Still open 👤, gating S7: C4, C9, C11, C21, C22 and the SignPath application; new by-hand rows C23–C27 |
| **Next approval stop** | End of S4 (A2) |

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
| S4: Final wheel | M2 | L | `[ ]` |
| S5: Toasts, tray, settings | M2 | L | `[ ]` |
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
- [ ] `ui/theme.py`
- [ ] `ui/wheel/renderer.py`
- [ ] `ui/wheel/animator.py`
- [ ] `ui/wheel/window.py` (final)
- [ ] Qt tests: alpha floor and hide-after-fade
- [ ] M2 checks 1, 2, 3, 6, 9
- [ ] Carry-over from S3: the sniffer's second `set_plan` repaints mid-drag; the final renderer keeps hover and arming across it (the session already does)

### S5: Surrounding UI (M2)
- [ ] `settings/model.py` and `settings/store.py`
- [ ] `ui/toasts/*` (S3 shipped the text-only model and manager; add the buttons Show in folder, Undo, Details, the working toast for a single long file, and the final look)
- [ ] Carry-over from S3: a download dialog for the HEIC engine (today `--install-heic` from a console, synchronous) and a catalog refresh after an install (today the app restarts); run the download off the GUI thread
- [ ] `ui/tray.py`
- [ ] `ui/settings_window.py`
- [ ] `ui/onboarding.py`
- [ ] `ui/dialogs.py`
- [ ] `platform/autostart.py` and `platform/single_instance.py`
- [ ] `i18n/`, RTL-ready per D3a
- [ ] **Re-allow the Qt `imageformats` plugins the icons need** (at least `qico`, and `qsvg` for SVG icons) in the spec. The S0 trim removed them, and a `QIcon` from an `.ico` would otherwise fail silently.
- [ ] M2 checks 4, 5, 7, 8

### S6: Plugin system (M3)
- [ ] `plugins/discovery.py`
- [ ] `plugins/registry.py`
- [ ] Plugins settings page and trust dialog
- [ ] `sys.path` scoping in the loader (in place since S3: the plugin dir is appended; S6 adds the trust gate)
- [ ] `examples/sample_plugin/`
- [ ] `docs/plugins.md`
- [ ] Crash and timeout tests

### S7: Release v0.1 (M4)
- [ ] Final `morphwheel.spec`
- [ ] `packaging/inno/morphwheel.iss`
- [ ] `.github/workflows/release.yml`
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
| RF-13 | Low | `core/wheel_session.py:261` | Hovering an EMPTY slot gives a DISABLED hub with `reason=None`. | Before S4 |
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
| 4 | Optional: upload the build to VirusTotal (this sends the file to a third party) | End of S0 |
| 5 | Decide whether to delete the temporary spike venv (`%LOCALAPPDATA%\Temp\twspk`, ~280 MB). Nothing uses it. | Any time |

## Open items to verify 🔶

| Item | Sprint |
|---|---|
| ~~`import ssl` works in the frozen app after the RF-1 fix~~ ✅ OpenSSL 3.0.16, 62 root certs, no network used. ~~A real HTTPS download is still unproven (S3, A6).~~ ✅ proven from source in S3 | S0 |
| ~~Worker cold start when frozen; `freeze_support` together with spawn~~ ✅ 0.17–0.20 s, works | S0 |
| ~~Separate Qt-free worker exe through `multiprocessing.set_executable`~~ ✅ built and proven by `--worker-check` on the frozen build (A5a) | S3 |
| ~~Memory use of the GUI plus 2 workers~~ ✅ 57 + 2×38.5 MB working set, frozen | S0 |
| Loading the pillow-heif `cp312` wheel from inside the frozen app (A6): ✅ from source (the download, the hash, the flat install and a 12 MP decode from an isolated interpreter). From the *frozen* worker: still unverified (needs the S5 dialog) | S0/S3 → S5 |
| ~~"Restart normally" from an elevated window~~ implemented (RD-6); 👤 C21 proves it | S2 |
| Per-element fade with no drop-transparent gap | S4 |
| DROPDESCRIPTION, to show "Convert to JPG" instead of "Copy" | S4 |
| Mica in settings; blur | S5 |
| Placing the onboarding bubble when the tray icon is in the overflow area | S5 |

## Work log (newest first)

- **2026-10-29 (S3 built)**
  - Plan written from phase-4 §4.4, §4.5 and §9, then attacked from two lenses before any code. The data-loss lens found two blocking holes in the §4.4 sketch (a killed worker leaving an empty `photo.jpg`; a 0-byte placeholder that isn't provably ours), fixed by delete-on-close placeholders and rename-only commits (RD-10). The process lens settled `set_executable` for a frozen child, the pool's wait on pipe plus sentinel, and the HEIC wheel's flat DLL layout.
  - Files 1–13 in the §9 order, each with its tests; then the toasts, the sniffer, the application wiring, the integrity gate (RD-8), the probe's swapped-button fix, contracts R2–R4, and the two-executable spec. 604 tests (182 new; 92 integration tests with real files and real worker processes).
  - The frozen build (83 MB) passes `--worker-check`: both workers run `morphwheel-worker.exe` with no Qt (A5a). Defender clean. Both exes carry `longPathAware`.
  - A6 proven from source: the pinned wheel downloaded (6.6 MB, 1.2 s), hash matched, installed flat; a 12 MP HEIC decoded to JPG in 0.7 s from an isolated interpreter.
  - Quality defaults measured (PSNR and size at each default and its neighbours) and Compress for PNG defined (RD-7). Conversion-time target proposed (T7).
  - A code review (high effort) on the working tree found 8 items, all fixed (a stat on the GUI thread in DragEnter, a leak for all-skipped jobs, queued tasks running after shutdown, tasks hanging when no worker starts, a stuck job when the pool refuses, dead code, a clumsy helper, a duplicated fixture). The security review found nothing above its bar; three hardening notes applied (plain-text toast labels, the file id in Undo, the engine folder appended to `sys.path`). Four cleanup lenses: 26 of 30 findings applied, 4 skipped with reasons. The frozen build was rebuilt from the final sources and re-checked.
  - Docs: S3 report, decisions RD-7 to RD-10 and T7, checklist rows C23–C27 and automated checks A4–A5, README (`--install-heic`), overview.
  - Yuval approved S3 with RD-7 to RD-10 and T7 (A2). Committed to `main` at Yuval's request; not pushed.

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
