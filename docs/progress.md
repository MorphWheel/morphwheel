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
| **Sprint** | S1 ✅ approved. **S2 is next** (M1). S0 is code-complete; two of its 👤 items are still open (S0-1) |
| **Current task** | Between sessions. Review findings RF-1–6, 8–10, 12 and 14 are fixed, and RD-1 to RD-3 are approved. Committed and pushed to `main` on 2026-10-22. |
| **Next** | S2 (OS hooks and dev wheel), once the 👤 items below are done. RF-7 and RF-15 come with S2. |
| **Blocked on** | **S2 is blocked** until the remaining S0 👤 items close: checklist C1–C12 and the SignPath application. Repo and CI are ✅ done. |
| **Next approval stop** | End of S2 (A2) |

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
| S0: Foundation | M0 | M | `[~]` code done, 👤 items open |
| S1: Pure core | M1 | M | `[x]` ✅ approved 2026-10-19 |
| S2: OS hooks and dev wheel | M1 | M | `[ ]` |
| S3: Engine and built-in converter | M1 | L | `[ ]` |
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
- [ ] Integration checklist v1 executed (👤 real drags):
  - [ ] Spike tests 4–6
  - [ ] Esc
  - [ ] Elevated window in the foreground
  - [ ] Multiple monitors, if available
  - [ ] **Re-measure on a local console session (not RDP)**
  - [x] Defender scan: no threats
- [x] License audit of the frozen bundle: no pillow-heif inside ✅; license texts are missing, so S7 adds them
- [ ] 👤 SignPath application submitted

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
- [ ] `platform/_win32.py`
- [ ] `platform/system.py`
- [ ] `platform/window_probe.py`
- [ ] `platform/raw_input.py`
- [ ] `platform/modifier_poller.py`
- [ ] `ui/wheel/window.py` (basic renderer)
- [ ] `app/controller.py` (partial)
- [ ] `app/application.py`
- [ ] "Restart normally" feasibility 🔶
- [ ] Carry-over from S1: DragEnter **always** goes through `force_copy` (Qt sends no DragMove after an ignored DragEnter); `accepts_drop` governs DragMove and Drop only
- [ ] Carry-over from S1: `more_center_deg` comes from `geometry.more_arc(center, screen, MORE_ARC_MAX)` (worst-case count)
- [ ] Carry-over from S1: feed `GiveUp` to the gesture machine when the session reports `GAVE_UP`

### S3: Engine and built-in converter (M1)
- [ ] `plugins/api.py`
- [ ] `plugins/manifest.py`
- [ ] `engine/integrity.py`
- [ ] `engine/file_ops.py`
- [ ] `plugins/loader.py`
- [ ] `builtin/pillow_images/plugin.toml`
- [ ] `builtin/pillow_images/converter.py`
- [ ] `engine/worker_main.py`
- [ ] `engine/worker_pool.py`
- [ ] `engine/dispatcher.py`
- [ ] `platform/shell.py`
- [ ] `engine/undo.py`
- [ ] `engine/engines.py` (opt-in HEIC download, A6)
- [ ] Minimal toast
- [ ] Fixtures and integration tests
- [ ] Define Compress for PNG; validate the quality defaults
- [ ] Add import-linter contracts R2, R3 and R4
- [ ] **Qt-free worker executable** (`morphwheel-worker.exe` + `set_executable`), because frozen workers load QtCore today (S0 Finding 1)
- [ ] Carry-over from RF-3: `candidate_paths()` needs the **sniffed** `source_format`. Add `source_format` to `Task` (a phase-4 §4.1 contract change, so propose it), filled from the plan's `FileInfo`, so the worker doesn't sniff again or fall back to the file name
- [ ] Carry-over from RF-10: `Task.options` is read-only (`MappingProxyType`), so don't use `dataclasses.asdict()` on a `Task`

### S4: Final wheel (M2)
- [ ] `ui/theme.py`
- [ ] `ui/wheel/renderer.py`
- [ ] `ui/wheel/animator.py`
- [ ] `ui/wheel/window.py` (final)
- [ ] Qt tests: alpha floor and hide-after-fade
- [ ] M2 checks 1, 2, 3, 6, 9

### S5: Surrounding UI (M2)
- [ ] `settings/model.py` and `settings/store.py`
- [ ] `ui/toasts/*`
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
- [ ] `sys.path` scoping in the loader
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
| RF-15 | Low | `packaging/pyinstaller/file_version_info.txt:26` | The version resource says `OriginalFilename=morphwheel.exe` but is attached to `drag_probe.exe`. | S2 (when the entry switches) |

A code review of the fixes found 8 more issues. 5 are fixed, including a name like `Dr. Who`, which lost ` Who`, and a guard compare that didn't resolve paths. The other 3 became RD-1 and the S3 carry-overs above.

**Decisions from the RF fixes:** RD-1 (a drop still counts toward arming; the More arc is frozen), RD-2 ("already compact" is not a failure) and RD-3 (names cut only a known image extension). ✅ Approved by Yuval 2026-10-19 and recorded in [`decisions.md`](decisions.md).

## Pending actions for Yuval 👤

| # | Action | Needed by |
|---|---|---|
| 1 | ~~Create the GitHub org `morphwheel` and a public repo~~ ✅ 2026-10-19: Yuval created the org; the public repo [MorphWheel/morphwheel](https://github.com/MorphWheel/morphwheel) was created, with private vulnerability reporting on | Done |
| 1b | ~~First commit and push~~ ✅ pushed to `main` at Yuval's request. Recommended: require 2FA for org members (Org settings → Authentication security) | Done (2FA: Yuval) |
| 2 | Apply to SignPath Foundation | After #1 |
| 3 | Run the manual drag checklist, including once on a local console session (not RDP) | End of S0 |
| 4 | Optional: upload the build to VirusTotal (this sends the file to a third party) | End of S0 |
| 5 | Decide whether to delete the temporary spike venv (`%LOCALAPPDATA%\Temp\twspk`, ~280 MB). Nothing uses it. | Any time |

## Open items to verify 🔶

| Item | Sprint |
|---|---|
| ~~`import ssl` works in the frozen app after the RF-1 fix~~ ✅ OpenSSL 3.0.16, 62 root certs, no network used. A real HTTPS download is still unproven (S3, A6). | S0 |
| ~~Worker cold start when frozen; `freeze_support` together with spawn~~ ✅ 0.17–0.20 s, works | S0 |
| Separate Qt-free worker exe through `multiprocessing.set_executable` | S3 |
| ~~Memory use of the GUI plus 2 workers~~ ✅ 57 + 2×38.5 MB working set, frozen | S0 |
| Loading the pillow-heif `cp312` wheel from inside the frozen app (A6) | S0/S3 |
| "Restart normally" from an elevated window | S2 |
| Per-element fade with no drop-transparent gap | S4 |
| DROPDESCRIPTION, to show "Convert to JPG" instead of "Copy" | S4 |
| Mica in settings; blur | S5 |
| Placing the onboarding bubble when the tray icon is in the overflow area | S5 |

## Work log (newest first)

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
