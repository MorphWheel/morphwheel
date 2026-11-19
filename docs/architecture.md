# Architecture

> The living English summary of the approved blueprint,
> [phase-4-architecture.md](discovery/phase-4-architecture.md) (Hebrew, archived). Where this page
> and the code disagree, the code wins and this page is wrong: fix it. Decisions are cited by ID
> from [decisions.md](decisions.md); the one-page product view is [overview.md](overview.md).

## 1. The layers and the dependency law

```
                ┌──────────────────────── app/ (the composition root) ────────────────────────┐
                │                                                                             │
   ui/ [Qt] ────┤   platform/ [Win32]       engine/ [conversion]      plugins/ [extensions]   │
       │        │        │                      │      │                     │                │
       └────────┴────────┴────────► core/ ◄─────┘      └── worker_main ───► plugins.api       │
                               (pure Python:               (no Qt)          (stdlib only)      │
                                no Qt, no Win32)                                               │
```

| Package | Role | May import |
|---|---|---|
| `core/` | The rules: formats, the catalog and slots, jobs, geometry, output naming, the gesture machine, the wheel session. Pure Python, tested as transition tables; time arrives on the events (`t_ns`) | the standard library only |
| `platform/` | Win32 through `ctypes`: raw input, the key poller, the window probe, elevation, the shell (Recycle Bin, Explorer), autostart, the single instance | `core`, `logs`; Qt only in the three `QObject` adapters (`raw_input`, `modifier_poller`, `single_instance`) |
| `engine/` | The worker pool and its supervisors, the worker process, file operations, the integrity guard, undo, the engine registry (HEIC), the dispatcher (the one `QObject` in `engine`) | `core`, `plugins`, `settings`, `logs` |
| `plugins/` | The public SDK (`api`), the manifest, discovery, the registry, the loader | `core`, `settings`; `api` uses the standard library alone |
| `builtin/` | The bundled converter (`pillow_images`), written against `plugins.api` like any plugin | `plugins.api`, Pillow |
| `ui/` | Qt: the wheel window with its renderer, animator, sniffer and drop guard; toasts; the tray; settings and dialogs; the theme | `core`, `settings`, `i18n`, `engine.undo` (the undo registry behind a toast's button); never `platform`, never the worker side (the pool, the worker, the dispatcher, the engines) |
| `settings/`, `logs.py`, `i18n/` | Paths, the settings model and store; the rotating log; translation loading | the standard library, `platformdirs` and `tomli_w`; Qt in `i18n` and in `settings/store.py` (its change signal) |
| `app/` | `Application` and `Controller`: the only modules that know every layer and wire them | everything |

The law is enforced by import-linter (`pyproject.toml`, six contracts, run on every push):

| Rule | Contract | What it holds |
|---|---|---|
| R1 | `core` is pure | no Qt, no `ctypes`, no other Morphwheel layer |
| P1 | `platform` is Qt-free except the three adapters | and imports no other layer above `core` |
| P2 | `ui` has no Win32 and wires nothing itself | no `ctypes`, no `platform`, no worker pool, no dispatcher, no `app` |
| R2 | the worker side never loads Qt or a GUI layer | `worker_main`, `worker_pool`, `file_ops`, `integrity`, `plugins.loader`, `plugins.api`, `builtin` |
| R3 | `plugins.api` is the public SDK | standard library only: nothing from Morphwheel, Pillow or the dependencies |
| R4 | only `app` wires the layers | a layers contract: `app` → `ui | platform` → `engine | builtin` → `plugins` → `core | settings | logs | i18n` |
| R5 | the GUI process never imports plugin code | not a linter rule: discovery reads `plugin.toml` and nothing else, held by a test with a plugin whose import raises |

## 2. Processes and threads

```
┌──────────────────────────── GUI process (morphwheel.exe) ──────────────────────────────┐
│ Qt main thread                                                                          │
│   RawInputMonitor (WM_INPUT) ─┐                                                         │
│   ModifierPoller (8 ms)      ─┼─► GestureMachine ─► WheelWindow + WheelSession          │
│                               │                          │ drop → DropRequest           │
│   Toasts · Tray · Settings ◄──┴── JobDispatcher ◄────────┘                              │
│ Sniffer thread     (header sniff after DragEnter; local paths only; 50 ms budget)       │
│ Supervisor threads (one per worker: send tasks, read results, timeouts, respawn)        │
└───────────────────────────────┬──────────────────────────────┬─────────────────────────┘
                     pipe (pickle) │                             │ pipe
                   ┌───────────────▼──────────┐       ┌──────────▼───────────────┐
                   │ morphwheel-worker.exe #1  │       │ morphwheel-worker.exe #2 │
                   │ loader → Converter.convert│       │ …                        │
                   │ reserve · temp · commit   │       └──────────────────────────┘
                   │ fingerprint before/after  │
                   └───────────────────────────┘
```

- **Nothing heavy on the main thread.** Raw Input arrives there, and Explorer is blocked until our
  drop handler returns, so the drop handler builds a `DropRequest` and nothing else (under 5 ms).
- **DragEnter does no I/O.** The first plan is by extension. The sniffer thread then reads up to
  64 KB of each local file (the real format, animated or not) within a 50 ms budget and the window
  re-plans; network paths are not sniffed. If the sniff has not finished by the drop, the worker
  reads the header itself.
- **Workers** are `multiprocessing` spawn processes (A5), warmed at start. In the frozen app they
  are a separate Qt-free executable, `morphwheel-worker.exe`, through
  `multiprocessing.set_executable` (A5a): PyInstaller's PySide6 runtime hook would otherwise load
  Qt into every spawn. `__main__.py` calls `freeze_support()` before any Qt import.
- **Isolation.** A worker that crashes or exceeds the task limit (120 s) is replaced; the task is
  reported `WORKER_CRASHED` or `TIMEOUT`, the GUI keeps running. Enabling, disabling or replacing a
  plugin respawns the workers, so no stale plugin module survives.
- **One instance per session:** a named mutex, `Local\Morphwheel`; a second start knocks on a named
  pipe and the first opens its settings. The installer names the same mutex (`AppMutex`).

### 2.1 The sequence: from a drag to a toast

```
Explorer     RawInput/Poller   GestureMachine   WheelWindow+Session    Dispatcher   Worker             Toasts/Undo
 L-down ──────► pointer_down ──► Pressed
 move ────────► pointer_moved ─► Dragging (the per-DPI threshold)
 Shift ───────► changed(True) ─► ShowWheel(x,y) ─► move + show (no activate)
 DragEnter ───────────────────────────────────► plan(ext) → sniff → plan'
 DragOver… ───────────────────────────────────► hover · arming (U7) · halo · More
 Drop ────────────────────────────────────────► decide_drop → force_copy → DropRequest
   (Explorer released, < 5 ms)                   fade → hide()        submit() ─► Task ─► reserve → temp
                                                                                           convert (plugin)
                                                                                           verify size + fingerprint
                                                                                           commit / abort
                                                                     JobResult ◄──────── TaskResult
                                                                          └───────────────────────────► toast + UndoRegistry
```

## 3. The contracts between the components

**What travels** (`core/jobs.py`, with `FileInfo` from `core/formats.py`): `FileInfo` (a dragged file
as the wheel knew it, with the sniffed format), `DropRequest` (the files, the target id, the time
received), `Task` (one file, one target, the options and the fallback folder; frozen, picklable,
read-only options), `TaskResult` (a `TaskStatus`, an `ErrorCode` from `core/errors.py` on failure,
the output path, a message for the log) and `JobResult` (every task's result;
`already_compact` listed apart from `failed`, RD-2). A `Task` carries the sniffed `source_format`
as a hint; the worker sniffs itself when it is `None` (RD-9).

**`core`** answers questions and never acts: `catalog` turns the dragged files into a slot plan
(disabled with a reason, skip counts for same-format files, U2); `geometry` places the wheel and
hit-tests slots and the halo; `gesture` returns `ShowWheel` / `HideWheel` commands from input events;
`wheel_session` turns pointer positions into a `SessionView` (what to paint, whether to accept the
drop) and makes the final `decide_drop`; `output_policy` names outputs (` (n)` on a clash,
` (compressed)` for Compress, D2, RD-3).

**`platform`** reports and performs, with no policy: `raw_input` (presses, releases, motion),
`modifier_poller` (the trigger key every 8 ms while a gesture is tracked; D8), `window_probe` (the
window class chain under the cursor and the pressed window's process id), `system` (elevation
type; the source process's integrity level from that id, RD-8; the drag threshold; the animation and High Contrast
switches; "Restart normally", RD-6), `shell` (Recycle Bin with undo, reveal in Explorer), `autostart` (the Run value, RD-23),
`single_instance`.

**`engine`**: `WorkerPool` (Qt-free; a supervisor thread per worker, a shared task queue, a duplex
pipe and the process sentinel, so a crash is seen at once); `worker_main` (one task at a time:
fingerprint, reserve, convert through the loader, verify, commit); `file_ops` (`reserve_unique`
with an exclusive create, a delete-on-close placeholder, a temp file and a rename-only commit,
RD-10); `integrity` (size, mtime, NTFS file id, and a SHA-256 up to 64 MB); `undo` (D5); `engines`
(the opt-in HEIC download, A6); `JobDispatcher` (one task per file, same-format files skipped, the
thread hop back to the GUI thread through a queued signal).

**`plugins`**: `api` is the whole SDK: a converter's `convert(ctx)` reads `ctx.input_path`, writes
only to `ctx.output_path` (a temp file Morphwheel chose) and reports through the API's errors.
`manifest` parses `plugin.toml` with its limits and reserved names; a third-party manifest is
namespaced and keeps no slot (an impostor builtin stays in the More arc). `discovery` lists the
builtin plugin and the user's folders without importing them (R5). `registry` is a pure function of
the discovery and the `plugins` settings: enabled iff listed, one stable order for the More arc,
a module-name clash refused deterministically (RD-26, RD-28). `loader` (workers only) imports a
plugin as one module or package inside its own folder, appended to `sys.path`, never shadowing the
app, Pillow or Python (RD-28).

**`ui`**: `WheelWindow` is pre-created, translucent, never focused, the only window shown during a
drag and the only drop target; every DragEnter goes through `drop_guard.force_copy` (phase-1 §3.3);
`renderer` paints from the theme's tokens over an alpha-1 floor, `animator` runs the appear, fade and
shrink and ends every fade in `hide()`, `sniffer` is the thread above. Toasts (`toasts/`) never take
focus and stack bottom-right of the drop's screen. The tray, the settings window, the onboarding and
the dialogs are ordinary non-modal windows; the only modal is the elevated warning before the
controller starts (RD-22).

**`settings`**: a typed `Settings` model with a schema number, loaded with per-field fallbacks and
saved atomically; a save re-reads the file and merges, so keys from a newer version and hand edits
survive (RD-15, RD-21). `paths` is the one place that knows the folders.

## 4. Files on disk

| What | Where |
|---|---|
| The installed app (per user) | `%LOCALAPPDATA%\Programs\Morphwheel\` |
| Settings | `%APPDATA%\Morphwheel\settings.toml`, saved atomically |
| The user's plugins | `%APPDATA%\Morphwheel\plugins\<plugin-id>\` |
| Logs | `%LOCALAPPDATA%\Morphwheel\logs\morphwheel.log`, rotating, 5 × 1 MB, local only |
| Engines | `%LOCALAPPDATA%\Morphwheel\engines\heic\` (the opt-in download, A6) |
| Fallback output folder | `Downloads\Morphwheel\` (the shell's Downloads, which follows a redirection) |
| Start with Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Morphwheel` |

## 5. Traceability: approved rule → component → test

| Rule | Source | Component | How it is held |
|---|---|---|---|
| `force_copy`, never Move | phase-1 §3.3 | `ui/wheel/drop_guard.py`, `window.py` | `tests/unit/test_drop_guard.py` (a 126-case matrix of modifiers × proposed actions); every DragEnter in `tests/qt/test_wheel_window.py`; by hand: the checklist |
| Never overwrite, even in a race | phase-2 §3.4 | `engine/file_ops.py` | `tests/unit/test_file_ops.py`: `reserve_unique` with a file created mid-way; no replace of a file that is not ours |
| ` (n)` on a name clash, ` (compressed)` | phase-2 §3.4, D2 | `core/output_policy.py` | `tests/unit/test_geometry_output.py` |
| A Compress output that is not smaller is discarded | phase-3 §2.2, RD-2 | `engine/worker_main.py` | `tests/integration/test_worker_main.py` (`test_compress_not_smaller_leaves_nothing`; the converter never judges size, the worker does) |
| Fallback folder for a read-only source folder | phase-2 §3.4 | `worker_main` + `output_policy` | `tests/integration/test_worker_main.py` (a locked folder falls back to Downloads) |
| Source integrity check | phase-2 §3.4 | `engine/integrity.py` + `worker_main` | `tests/unit/test_integrity.py`; a tampering fixture plugin → `SOURCE_CHANGED` (`test_worker_main.py`, `tests/qt/test_plugin_failures.py`) |
| Limited undo, this session only | D5 | `engine/undo.py` + `platform/shell.py` | `tests/unit/test_undo.py` (a changed file is refused); `test_shell.py` (no Recycle Bin → refused); by hand: the Recycle Bin |
| Disabled source, skips in a mixed drag, incompatible | U2 | `core/catalog.py` | `tests/unit/test_catalog_jobs.py` |
| Eight fixed slots, More, plugins only in the More arc | U2, U3 | `catalog` + `plugins/manifest.py`, `discovery.py` | `tests/unit/test_catalog_jobs.py` (every plan has all eight slots; a third party cannot claim a fixed one); `test_manifest.py` (an impostor builtin stays in the More arc); `test_discovery.py` (a taken id is reported broken, a slot claim ignored) |
| Sticky wheel, cancel in the hub, leaving the halo closes, a new Shift reopens | U1 | `core/gesture.py` + `wheel_session.py` | `tests/unit/test_gesture.py`, `test_wheel_session.py` (transition tables) |
| Arming after 12 px | U7 | `core/wheel_session.py` | `tests/unit/test_wheel_session.py` |
| Placement against the screen, the More arc turns inward | phase-3 §2.1 | `core/geometry.py` | `tests/unit/test_geometry_output.py` |
| **Alpha floor ≥ 1**, no window-level opacity | phase-3 C2, C3 | `ui/wheel/renderer.py` + `animator.py` | `tests/qt/test_renderer.py`, `test_wheel_window.py`: offscreen `QImage` renders in every state and mid-fade frame; alpha ≥ 1 on the disc and the halo, 0 outside |
| `hide()` at the end of every fade | phase-3 C3 | `animator.py` + `window.py` | `tests/qt/test_wheel_window.py`: after a fade `isVisible()` is false; a show mid-fade is never hidden by the old fade |
| One window during a drag, no tooltips | phase-3 C1 | `ui/wheel/window.py` | code review; `test_wheel_window.py` holds that `QToolTip` is unused |
| Resizing S/M/L only while hidden | U4 | `WheelWindow.apply_size`, wired in `app/application.py` | `tests/qt/test_wheel_window.py` (`test_size_changes_only_while_hidden`) |
| The elevated check at start | phase-2 §3.7 | `app/application.py` + `platform/system.py` | `tests/unit/test_system.py`; by hand: C21 |
| `runasoriginaluser` in the installer | phase-2 §3.7 | `packaging/inno/morphwheel.iss` | `tests/unit/test_installer.py` (the flags); by hand: C42, C43 |
| The GUI never imports plugin code | R5 | `plugins/discovery.py` | `tests/unit/test_discovery.py`: a plugin whose import raises is discovered untouched |
| Animations off: zero duration | phase-3 C7 | `animator.py` + `platform/system.py` | `tests/qt/test_wheel_window.py`, `test_animator.py` |
| Pause from the tray: drags ignored, the poller stops | phase-2 §3.1 | `app/controller.py` | `tests/qt/test_controller.py` (a fake monitor) |
| The trigger key choice reaches the poller at once | D8 | `controller` + `settings/store.py` | `tests/qt/test_settings_signals.py`, `test_controller.py` |
| The hub repeats the hovered target | phase-3 C5 | `renderer.py` + `SessionView` | `tests/qt/test_renderer.py` |
| Hide on a release without a drop, as soon as the outcome is known (a 150 ms grace for the drop event) | phase-2 §3.2 | `GestureMachine` (`PointerUp`, `RELEASING`) + `animator` | `tests/unit/test_gesture.py`, `tests/qt/test_wheel_window.py` |
| Waiting state: a spinner after 150 ms, "Can't read this drag" after 1.5 s | phase-3 §4 | `wheel_session.py` (timers as data) + `renderer` | `tests/unit/test_wheel_session.py` |
| A lower-integrity drag source is refused | RD-8 | `platform/system.py` (`source_integrity_ok`) + `controller` | `tests/unit/test_system.py` (the rule is exact; an unreadable level never breaks a drag) |
| A plugin is one module or package in its own folder; no shadowing | RD-28 | `plugins/loader.py`, `manifest.py`, `registry.py` | `tests/unit/test_loader.py`, `test_manifest.py`, `test_registry.py` |
| A crashed, hung, broken or tampering plugin leaves nothing behind | M3 | the pool, the worker, the toasts | `tests/qt/test_plugin_failures.py`: the four fixture plugins through the real app and real workers |

"phase-3 C*n*" are the constraints of [phase-3-ux.md](discovery/phase-3-ux.md); the manual checklist
rows C1 to C43 (a different numbering) are in
[testing/integration-checklist.md](testing/integration-checklist.md).

## 6. Tests and CI

- **Unit** (`tests/unit/`): the pure core as transition tables, the Win32 layer's pure parts, the
  manifests, the file operations, the packaging and release tooling, the release documents.
- **Qt** (`tests/qt/`): offscreen (`QT_QPA_PLATFORM=offscreen`, set by `tests/conftest.py`) with
  `pytest-qt`; the wheel is rendered to a `QImage` and its pixels asserted.
- **Integration** (`tests/integration/`): real files, real worker processes, a crash, a hang, a
  timeout, the fixture plugins; the builtin converter over generated images (nothing binary is
  checked in).
- **Gates** on every push (`.github/workflows/ci.yml`, windows-latest): ruff, ruff format, mypy
  strict, import-linter, pytest. The same five run locally before every report.
- **Live drags** are performed by the user with `tools/drag_probe.py` and the checklist; the
  session reads the logs.

## 7. Packaging and release

- **PyInstaller onedir** (`packaging/pyinstaller/morphwheel.spec`): no UPX, a version resource held to
  `__version__`, the app icon (RD-29), the builtin plugin as data, the license texts collected into
  `licenses/` (`bundle_licenses.py`, RD-33), the Qt plugins trimmed to what the app uses, and
  pillow-heif on the exclusion list (A6). `morphwheel.exe --worker-check` proves both workers
  Qt-free (A5a). Targets: GUI ≤ 70 MB and workers ≤ 35 MB of private bytes idle (T5a); the
  installer download ≤ 45 MB (T6).
- **Inno Setup** (`packaging/inno/morphwheel.iss`, RD-30): the compile fails if the dist carries
  pillow-heif (A6); per user, `PrivilegesRequired=lowest`,
  into `%LOCALAPPDATA%\Programs\Morphwheel`, a full elevated token refused, "Launch" as the original
  user, the *Start with Windows* task as an exact setter of the Run value, `_internal` cleaned on
  upgrade, the uninstaller asking before deleting the user's data.
- **The release workflow** (`.github/workflows/release.yml`, `tools/release.py`, RD-31): a `v*` tag
  builds, checks the tag against `__version__`, asserts pillow-heif is not importable in the build
  environment (A6), signs through SignPath when the repository is
  configured for it, packs the installer, writes `SHA256SUMS.txt` and the notes from
  `CHANGELOG.md`, renders the winget manifests (RD-32), and leaves a draft GitHub Release.
  Publishing the draft and the winget-pkgs PR are human steps.

## 8. Risks that shaped the design

- **Explorer's drag loop is blocked while our drop handler runs:** hence the sub-5 ms handler and
  the sniffer thread.
- **A drop-transparent hole or frame** would let a drop fall through to the folder below as a
  move: hence the alpha-1 floor, no window-level opacity, and `hide()` only at the end of a fade.
- **Frozen is not source:** PyInstaller's runtime hooks load Qt into spawned workers, hence the
  separate worker executable; the frozen build is measured, not assumed.
- **Licensing:** pillow-heif's wheels bundle GPL codecs, hence the opt-in download; Qt is LGPL and
  dynamically linked; every shipped text is collected at build time and listed in
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
- **Antivirus false positives** on a PyInstaller build: no UPX, a version resource, a Defender scan
  of every measured build, and code signing once SignPath approves.
