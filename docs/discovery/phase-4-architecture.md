# שלב 4: ארכיטקטורת תוכנה ו-blueprint

**פרויקט:** Morphwheel
**תאריך:** 19.10.2026
**סטטוס:** ✅ אושר ב-19.10.2026, עם כל ההמלצות (A1–A6). זה האור הירוק ל-Phase 5. ההחלטות מפורטות ב-§12.

**מבוסס על** ההחלטות שאושרו ב:
- [שלב 1](phase-1-research.md#7-החלטות-שאושרו-19102026)
- [ה-spike](phase-1b-spike-results.md)
- [שלב 2](phase-2-concept.md#8-החלטות-שאושרו-19102026)
- [שלב 3](phase-3-ux.md#11-החלטות-שאושרו-19102026)

**הערות למסמך:**
- **שמות:** שמות קבצים, מחלקות ופונקציות באנגלית.
- **חתימות:** החתימות כאן הן **טיוטת חוזים** בלי מימוש. הן יכולות להשתנות מעט ב-Phase 5, אבל כל שינוי בחוזה ציבורי (plugin API) יחזור לאישורך.

**מקרא תגיות:**
- ✅ מאומת: מקומית, ב-spike, או במקור ראשוני
- 🔶 הנחה שתיבדק ב-sprint שמצוין לידה

---

## תקציר

- **ארבעה מודולים לפי ה-brief**, ועוד ליבה נקייה:

  | מודול | תיקייה | תוכן |
  |---|---|---|
  | **GUI** | `ui/` | הגלגלת, ה-toasts, ה-tray וההגדרות |
  | **OS hooks** | `platform/` | Raw Input, ‏polling, ‏Win32 |
  | **מנועי המרה** | `engine/` + `builtin/` | worker pool והממיר של Pillow |
  | **הרחבות** | `plugins/` | ה-API הציבורי, manifest וטעינה |
  | **ליבה** | `core/` | כל כללי ההתנהגות, בלי Qt ובלי Win32. נבדקת ב-unit tests על כל מערכת הפעלה. |

- **הפרדת תלויות נאכפת ב-CI** עם import-linter.
- **שני סוגי תהליכים:**
  - **תהליך GUI** (thread ראשי של Qt). מקבל את הקלט, מציג את הגלגלת ומחזיר את ה-drop תוך פחות מ-5ms.
  - **pool של 2 תהליכי worker.** ממירים בהם, ושם בלבד נטען קוד של plugins. ‏worker שקורס או נתקע מוחלף, והאפליקציה ממשיכה לרוץ.
- **טבלת מעקב (§6):** לכל כלל שאושר בשלבים 2–3 יש רכיב אחראי ובדיקה שמגינה עליו.
- **8 sprints (S0–S7) על המיילסטונים M0–M4.** לכל sprint יש רשימת קבצים מסודרת, שהיא סדר הכתיבה ב-Phase 5, ונקודת אישור בסופו.
- **6 החלטות מחכות לך ב-§11.** אחת מהן (A6) נובעת מממצא רישוי חדש: ה-wheels של pillow-heif מגיעים עם x265 ברישיון GPLv2.

---

## 1. עקרונות וחוק התלויות

```
                ┌───────────────────────────── app/ (composition root) ─────────────────────────────┐
                │                                                                                    │
   ui/ [GUI] ───┤   platform/ [OS hooks]        engine/ [conversion]        plugins/ [extensions]    │
       │        │        │                         │      │                       │                  │
       └────────┴────────┴──────────► core/ ◄──────┘      └── worker_main ──► plugins.api (stdlib)   │
                                   (pure Python:                 (no Qt)                              │
                                    no Qt, no Win32)                                                  │
```

| # | חוק | נאכף על ידי |
|---|---|---|
| R1 | ‏`core` לא מייבא PySide6, ‏ctypes של Win32, ולא אף מודול אחר של Morphwheel | import-linter (`forbidden`) |
| R2 | ‏`engine.worker_main` ומה שהוא מייבא לא מייבאים PySide6 | import-linter |
| R3 | ‏`plugins.api` משתמש ב-stdlib בלבד. זה ה-SDK הציבורי. | import-linter |
| R4 | רק `app/` מחבר בין המודולים. ‏`ui` לא מייבא את `engine.worker_pool` ישירות. | import-linter (`layers`) |
| R5 | תהליך ה-GUI **לא מייבא לעולם קוד של plugin.** הוא קורא רק `plugin.toml`. | code review + test |

---

## 2. מבנה התיקיות

ה-repo root הוא התיקייה הזו (‏A1). ‏`docs/discovery/` נשארת כמו שהיא.

```
<repo root>/
├─ pyproject.toml            build (hatchling), deps, ruff, mypy, pytest, import-linter contracts
├─ LICENSE  README.md  CHANGELOG.md  SECURITY.md  PRIVACY.md
├─ docs/
│  ├─ discovery/             phases 1–4 (this folder)
│  ├─ architecture.md        living summary of this blueprint (S7)
│  ├─ plugins.md             "write a converter in 30 lines" (S6)
│  └─ testing/integration-checklist.md   manual drag tests (S0, grows each sprint)
├─ src/morphwheel/
│  ├─ __main__.py            freeze_support() FIRST, then lazy-import app (no Qt at module top)
│  ├─ logs.py                logging setup, rotating file, timing helpers
│  ├─ app/          ── composition root ──────────────────────────────────────────────
│  │  ├─ application.py      QApplication, single instance, startup checks, shutdown
│  │  └─ controller.py       wires monitor → gesture → wheel → dispatcher → toasts/undo
│  ├─ core/         ── pure domain (no Qt / no Win32) ─────────────────────────────────
│  │  ├─ formats.py          FormatId, extension map, header sniffing (bytes in → id out)
│  │  ├─ catalog.py          Target, Catalog.plan() → WheelPlan (U2 rules)
│  │  ├─ geometry.py         WheelGeometry(scale), hit-test regions, clamp-by-disc
│  │  ├─ gesture.py          GestureMachine (Idle/Pressed/Dragging/WheelOpen/Dismissed) — U1
│  │  ├─ wheel_session.py    hover, arming (U7), More-arc dwell, halo, decide_drop()
│  │  ├─ output_policy.py    naming, " (n)" collisions, " (compressed)", fallback decision
│  │  ├─ jobs.py             DropRequest, Task, TaskResult, JobResult, CreatedFile
│  │  └─ errors.py           ErrorCode enum + user-facing message keys
│  ├─ platform/     ── [OS hooks] Win32 adapters ─────────────────────────────────────
│  │  ├─ _win32.py           ctypes signatures (user32/ole32/shell32/advapi32/kernel32)
│  │  ├─ raw_input.py        RawInputMonitor (native event filter + INPUTSINK sink window)
│  │  ├─ modifier_poller.py  ModifierPoller (8 ms GetAsyncKeyState, only while dragging)
│  │  ├─ window_probe.py     source_info_at(): class chain + allow/deny
│  │  ├─ system.py           elevation, drag threshold per DPI, animations, high contrast
│  │  ├─ shell.py            recycle bin (FOF_ALLOWUNDO), reveal in Explorer, Downloads path
│  │  ├─ autostart.py        HKCU\…\Run get/set
│  │  └─ single_instance.py  named mutex + QLocalServer "open settings" ping
│  ├─ engine/       ── [conversion engines] ─────────────────────────────────────────
│  │  ├─ dispatcher.py       JobDispatcher (GUI side): DropRequest → tasks → JobResult
│  │  ├─ worker_pool.py      WorkerPool + supervisor thread (spawn, timeout, respawn)
│  │  ├─ worker_main.py      worker loop (no Qt): load converter, run, report
│  │  ├─ file_ops.py         reserve_unique (exclusive create), temp path, commit/abort
│  │  ├─ integrity.py        fingerprint(size, mtime_ns, sha256≤64 MB), compare
│  │  └─ undo.py             UndoRegistry (session-scoped) → platform.shell recycle
│  ├─ plugins/      ── [extensions] ─────────────────────────────────────────────────
│  │  ├─ api.py              PUBLIC SDK (stdlib only, versioned)
│  │  ├─ manifest.py         plugin.toml schema + validation (tomllib)
│  │  ├─ discovery.py        scan builtin + user plugin dirs → manifests (no import)
│  │  ├─ registry.py         enabled/order from settings → Targets for the Catalog
│  │  └─ loader.py           WORKER ONLY: sys.path scoping, import entry, cache
│  ├─ builtin/
│  │  └─ pillow_images/      plugin.toml + converter.py (JPG PNG WebP AVIF ICO PDF Compress)
│  ├─ ui/           ── [GUI] ──────────────────────────────────────────────────────────
│  │  ├─ theme.py            WinUI tokens, scheme (QStyleHints), accent, high contrast
│  │  ├─ wheel/
│  │  │  ├─ window.py        WheelWindow: pre-created drop target, the ONLY drag-time window
│  │  │  ├─ drop_guard.py    force_copy() — the Phase-1 §3.3 rule, isolated for testing
│  │  │  ├─ renderer.py      paint(view, theme, anim) — alpha floor always painted
│  │  │  └─ animator.py      per-element progress; 0 ms when animations are off; ends in hide()
│  │  ├─ toasts/             model.py · widget.py · manager.py (stack ≤ 3, timers, buttons)
│  │  ├─ tray.py             icon states + menu
│  │  ├─ settings_window.py  General · Conversion · Plugins · About
│  │  ├─ onboarding.py       first-run bubble (anchored to work-area corner)
│  │  └─ dialogs.py          elevated warning, plugin trust prompt
│  ├─ settings/
│  │  ├─ model.py            Settings dataclasses + schema version
│  │  ├─ store.py            TOML load/save (atomic), change signal
│  │  └─ paths.py            platformdirs locations
│  └─ i18n/                  tr() helper + translations/ (.ts → .qm), English only in v0.1
├─ tests/
│  ├─ unit/                  core (transition tables), drop_guard matrix, output_policy, manifest
│  ├─ qt/                    pytest-qt offscreen: wheel render alpha-floor, toasts, settings
│  ├─ integration/           worker pool + real conversions on fixtures, integrity, collisions
│  └─ fixtures/              tiny PNG/JPG/HEIC/AVIF/animated GIF/corrupt files
├─ examples/sample_plugin/   plugin.toml + converter.py (S6)
├─ tools/drag_probe.py       dev-only diagnostic (successor of the spike; not shipped)
├─ packaging/
│  ├─ pyinstaller/morphwheel.spec    onedir, no UPX, version resource, builtin plugin as data
│  ├─ inno/morphwheel.iss            per-user, PrivilegesRequired=lowest, runasoriginaluser
│  └─ winget/                        manifest templates
└─ .github/workflows/        ci.yml (every push) · release.yml (tags: build → sign → publish)
```

---

## 3. מודל התהליכים וה-threads

```
┌──────────────────────────── GUI process (morphwheel.exe) ────────────────────────────┐
│ Qt main thread                                                                        │
│   RawInputMonitor (WM_INPUT) ─┐                                                       │
│   ModifierPoller (8 ms timer) ─┼─► GestureMachine ─► WheelWindow + WheelSession       │
│                                │                         │ drop → DropRequest (<5 ms) │
│   Toasts · Tray · Settings ◄───┴── JobDispatcher ◄───────┘                            │
│ Sniffer thread   (async header sniff after DragEnter; local paths only, 50 ms budget) │
│ Supervisor thread (WorkerPool: send tasks, read results, timeouts, respawn)           │
└───────────────────────────────┬──────────────────────────────┬──────────────────────┘
                     Pipe (pickle) │                              │ Pipe
                   ┌───────────────▼─────────┐        ┌───────────▼─────────────┐
                   │ worker #1 (no Qt)        │        │ worker #2 (no Qt)        │
                   │ loader → Converter.convert│        │ …                        │
                   │ reserve/temp/commit       │        └──────────────────────────┘
                   │ fingerprint before/after  │
                   └──────────────────────────┘
```

- **שום עבודה כבדה ב-thread הראשי.** ‏Raw Input מגיע ל-thread הראשי, ו-Explorer חסום כל עוד ה-Drop שלנו לא חזר. ✅ (spike)
- **DragEnter לא עושה קלט/פלט.**
  - הסיווג הראשוני הוא לפי סיומת בלבד.
  - בדיקת header (סוג אמיתי, האם התמונה מונפשת) רצה ב-sniffer thread. כשהיא מסתיימת, המשבצות מתעדכנות.
  - כוננים ברשת (UNC) לא נבדקים. אם הבדיקה לא הסתיימה עד ה-drop, ה-worker מאמת בעצמו ומחזיר שגיאה מסודרת.
- **Workers:**
  - נוצרים בשיטת `spawn` של multiprocessing, ומתחממים כבר בעליית האפליקציה.
  - **הזמן שלוקח ל-worker לעלות בגרסה ארוזה (PyInstaller) לא ידוע** 🔶. נמדד ב-S0.
  - `__main__.py` קורא ל-`freeze_support()` לפני כל import של Qt 🔶 (נבדק ב-S0).
- **בידוד ‏(M3):**
  - ‏worker שקורס או עובר את ה-timeout (ברירת מחדל 120s) מוחלף. המשימה מסומנת `WORKER_CRASHED` או `TIMEOUT`.
  - ה-GUI ממשיך לרוץ.

### 3.1 רצף: מגרירה ועד toast

```
Explorer      RawInput/Poller   GestureMachine   WheelWindow+Session   Dispatcher   Worker            Toasts/Undo
 L-down ───────► pointer_down ──► Pressed
 move ─────────► pointer_moved ─► Dragging (threshold, per-DPI)
 Shift ────────► changed(True) ─► ShowWheel(x,y) ─► move+show (no activate)
 DragEnter ─────────────────────────────────────► plan(ext) → sniff → plan'
 DragOver… ─────────────────────────────────────► hover · arming(U7) · halo · More
 Drop ──────────────────────────────────────────► decide_drop → force_copy → DropRequest
   (Explorer released, < 5 ms)                     fade → hide()   submit() ─► Task ─► reserve → temp
                                                                                       convert (plugin)
                                                                                       verify size/integrity
                                                                                       commit / abort
                                                                   JobResult ◄──────── TaskResult
                                                                        └──────────────────────────────► toast + UndoRegistry
```

---

## 4. ממשקים בין הרכיבים (טיוטת חוזים)

### 4.1 ‏`core/jobs.py`: מה שעובר בין הרכיבים

```python
@dataclass(frozen=True)
class DropRequest:
    files: tuple[Path, ...]          # local paths from DragEnter/Drop
    target_id: str                   # e.g. "jpeg", "compress", "com.jdoe.heicpro:tiff"
    received_at_ns: int

@dataclass(frozen=True)
class Task:
    job_id: str; task_id: int
    source: Path; target: Target
    options: Mapping[str, object]    # quality / compress preset from settings
    fallback_dir: Path               # Downloads\Morphwheel
    hash_limit_bytes: int = 64 * 2**20

@dataclass(frozen=True)
class CreatedFile:
    path: Path; size: int; mtime_ns: int; source: Path

@dataclass(frozen=True)
class TaskResult:
    job_id: str; task_id: int; source: Path
    status: Literal["ok", "skipped", "failed"]
    output: CreatedFile | None
    error: ErrorCode | None; detail: str | None   # detail → log only
    used_fallback: bool
    source_intact: bool                           # integrity guard verdict
    duration_ms: float

@dataclass(frozen=True)
class JobResult:
    job_id: str; target: Target
    results: tuple[TaskResult, ...]               # → one toast (single/batch/partial/error)
```

‏`ErrorCode`: ‏`UNREADABLE`, ‏`UNSUPPORTED_ANIMATED`, ‏`NOT_SMALLER`, ‏`WRITE_FAILED`, ‏`NO_SPACE`, ‏`TIMEOUT`, ‏`WORKER_CRASHED`, ‏`PLUGIN_ERROR`, ‏`SOURCE_CHANGED`.

### 4.2 ‏`core`: הלוגיקה (נבדקת בטבלאות מעברים)

```python
class GestureMachine:                     # U1 sticky + halo dismiss + re-open
    def feed(self, ev: PointerDown | PointerMove | PointerUp | ModifierState | WheelLeft | DropDone
             ) -> list[ShowWheel | HideWheel]: ...
    state: Literal["idle", "pressed", "dragging", "wheel_open", "dismissed"]

class Catalog:
    def __init__(self, targets: Iterable[Target]) -> None: ...
    def plan(self, files: Sequence[FileInfo]) -> WheelPlan: ...   # U2: source/incompatible/skip

class WheelGeometry:
    def __init__(self, scale: float) -> None: ...                  # S/M/L = 0.85/1.0/1.2
    def region(self, p: Point) -> Region: ...   # Hub | Slot(pos) | Gap | MoreItem(i) | Halo | Outside
    def clamp_center(self, cursor: Point, screen: Rect) -> Point: ...   # by DISC radius, not window

class WheelSession:
    def __init__(self, geometry: WheelGeometry, appear_at: Point, t0_ns: int) -> None: ...
    def set_plan(self, plan: WheelPlan) -> None: ...
    def on_pointer(self, p: Point, t_ns: int) -> SessionView: ...  # hover, armed(U7), more_open, halo_edge
    def decide_drop(self, p: Point, t_ns: int) -> Accept | Cancel: ...

def plan_output_candidates(src: Path, target: Target) -> Iterator[Path]: ...
    # "photo.jpg", "photo (1).jpg", …  |  compress: "photo (compressed).jpg", "photo (compressed) (1).jpg"
```

### 4.3 ‏`platform`: ‏OS hooks (ב-thread הראשי של ה-GUI)

```python
class RawInputMonitor(QObject):           # RegisterRawInputDevices(INPUTSINK) on a hidden sink window
    pointer_down = Signal(int, int)       # physical px (GetCursorPos)
    pointer_moved = Signal()
    pointer_up = Signal()

class ModifierPoller(QObject):            # runs only while gesture state ≠ idle
    changed = Signal(bool)
    def set_key(self, key: Literal["shift", "ctrl", "ctrl+shift"]) -> None: ...

def source_info_at(x: int, y: int) -> SourceInfo: ...       # class chain, allowed (Explorer/Desktop)
def drag_threshold_at(x: int, y: int) -> tuple[int, int]: ... # GetSystemMetricsForDpi
def is_elevated() -> bool: ...
def restart_unelevated() -> bool: ...                       # 🔶 S2 (Phase 3 §6.4 put it in M1)
def animations_enabled() -> bool: ...; def high_contrast() -> bool: ...
def move_to_recycle_bin(path: Path) -> bool: ...; def reveal_in_explorer(path: Path) -> None: ...
def downloads_dir() -> Path: ...                            # SHGetKnownFolderPath(FOLDERID_Downloads)
```

### 4.4 ‏`engine`: מנועי המרה

```python
class JobDispatcher(QObject):             # GUI side
    job_started = Signal(str, int)        # job_id, task count
    job_progress = Signal(str, int, int)  # job_id, done, total
    job_finished = Signal(object)         # JobResult
    def submit(self, req: DropRequest) -> str: ...   # splits per file; same-format files → "skipped"

class WorkerPool:                         # owns N spawn-processes + supervisor thread
    def __init__(self, size: int = 2, task_timeout_s: float = 120) -> None: ...
    def run(self, task: Task, done: Callable[[TaskResult], None]) -> None: ...
    def shutdown(self, timeout_s: float = 3) -> None: ...

# worker_main.py (no Qt) — per task:
#   fp0 = fingerprint(src) → res = reserve_unique(candidates) → tmp = res.temp_path
#   converter.convert(ctx(input=src, output=tmp)) → [compress: size(tmp) < size(src) else abort NOT_SMALLER]
#   fp1 = fingerprint(src); source_intact = (fp0 == fp1) → commit(res) | abort(res)

def reserve_unique(candidates: Iterator[Path]) -> Reservation: ...  # open(path, "xb") = atomic claim
def commit(res: Reservation) -> CreatedFile: ...                    # os.replace(temp → reserved final)
def abort(res: Reservation) -> None: ...                            # remove temp + placeholder

class UndoRegistry:                       # session-scoped (not persisted across restart)
    def record(self, job_id: str, files: Sequence[CreatedFile]) -> None: ...
    def undo(self, job_id: str) -> UndoOutcome: ...   # only recorded paths; size+mtime must match
```

### 4.5 ‏`plugins`: ה-API הציבורי והחוזה

```python
# plugins/api.py — stdlib only. Plugin authors import ONLY this module.
API_VERSION = (0, 1)

class ConversionContext(Protocol):
    @property
    def input_path(self) -> Path: ...       # read-only by contract
    @property
    def output_path(self) -> Path: ...      # temp file chosen by Morphwheel; write here only
    @property
    def target_id(self) -> str: ...
    @property
    def options(self) -> Mapping[str, object]: ...
    def progress(self, fraction: float) -> None: ...

class Converter(Protocol):
    def convert(self, ctx: ConversionContext) -> None: ...

class ConversionError(Exception):           # message shown in the toast
    ...
```

```toml
# plugin.toml — read by the GUI with tomllib; the GUI never imports plugin code (R5)
[plugin]
id = "com.jdoe.heicpro"
name = "HEIC Pro"
version = "1.2.0"
api = "0.1"                 # 0.x: major AND minor must match; ≥1.0: major must match
entry = "heic_pro:Converter"  # imported in workers only

[[targets]]
id = "tiff"
label = "TIFF"
output_ext = ".tiff"
accepts = ["heic", "heif"]  # v0.1: built-in FormatIds only
# slot = "N"                # honored ONLY for manifests discovered under the bundled builtin/ dir
                            # (decided by location, never by id); elsewhere → ignored, More arc (U3)
```

- **ה-plugin המובנה** `builtin/pillow_images` משתמש באותו API בדיוק. כך ה-API נבדק כבר מ-S3.

### 4.6 ‏`ui` ו-`settings`

```python
class WheelWindow(QWidget):               # Tool|Frameless|StaysOnTop|DoesNotAcceptFocus, translucent
    drop_requested = Signal(object)       # DropRequest
    left = Signal()                       # DragLeave with the button STILL DOWN (pointer left the halo)
                                          #   → GestureMachine(WheelLeft). A DragLeave caused by a
                                          #   release over hub/halo (spike: OLE sends DragLeave, not Drop)
                                          #   is a cancel, not a dismiss.
    def show_at(self, physical_xy: tuple[int, int]) -> None: ...
    def apply_size(self, size: Literal["S", "M", "L"]) -> None: ...   # only while hidden
    def fade_out_and_hide(self) -> None: ...

class ToastManager(QObject):
    def show(self, model: ToastModel) -> ToastHandle: ...   # working/success/batch/partial/error/…
    undo_clicked = Signal(str)            # job_id

@dataclass
class Settings:
    schema: int = 1
    trigger_key: Literal["shift", "ctrl", "ctrl+shift"] = "shift"
    wheel_size: Literal["S", "M", "L"] = "M"
    start_with_windows: bool = False
    paused: bool = False
    onboarding_done: bool = False
    quality: Quality = Quality(jpeg=90, webp=85, avif=70)
    compress: Compress = Compress(longest_side=2048, quality=80)
    plugins: PluginPrefs = PluginPrefs(enabled=[], order=[])
```

---

## 5. קבצים על הדיסק

| מה | איפה |
|---|---|
| התקנה (למשתמש בודד) | `%LOCALAPPDATA%\Programs\Morphwheel\` |
| הגדרות | `%APPDATA%\Morphwheel\settings.toml`. נשמר אטומית (temp ואז replace). |
| plugins של המשתמש | `%APPDATA%\Morphwheel\plugins\<plugin-id>\` |
| לוגים | `%LOCALAPPDATA%\Morphwheel\logs\morphwheel.log`. ‏rotating, ‏5×1MB, מקומי בלבד. נתיבי קבצים לא יוצאים מהמחשב. |
| מיקום חלופי לפלט | `Downloads\Morphwheel\`, לפי `FOLDERID_Downloads` |
| הפעלה עם Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Morphwheel` |

---

## 6. טבלת מעקב: כלל שאושר → רכיב → בדיקה

| כלל | מקור | רכיב אחראי | איך מוגן |
|---|---|---|---|
| ‏`force_copy`, לעולם לא Move | שלב 1 §3.3 | `ui/wheel/drop_guard.py` | unit: מטריצת מקשים × פעולות אפשריות (QDropEvent סינתטי). ידני: רשימת הבדיקות. |
| אף פעם לא דורסים, גם במרוץ | שלב 2 §3.4 | `engine/file_ops.py` | integration: ‏`reserve_unique` עם קובץ שנוצר באמצע. אין `os.replace` על קובץ שלא שלנו. |
| ` (n)` בהתנגשות שם, ‏` (compressed)` | שלב 2 §3.4, ‏D2 | `core/output_policy.py` | unit |
| פלט Compress שלא קטן יותר נמחק | שלב 3 §2.2 | `engine/worker_main.py` | integration (PNG קטן) |
| מיקום חלופי לתיקייה לקריאה בלבד | שלב 2 §3.4 | `worker_main` + `output_policy` | integration (תיקייה עם ACL לקריאה בלבד) |
| בדיקת שלמות קובץ המקור | שלב 2 §3.4 | `engine/integrity.py` + `worker_main` | integration: ‏plugin בדיקה "זדוני" שמשנה את המקור מוביל ל-`SOURCE_CHANGED` ולהתראה קריטית |
| Undo מוגבל, לסשן בלבד | D5 | `engine/undo.py` + `platform/shell.py` | unit (קובץ שהשתנה → סירוב), ידני (סל המחזור) |
| מקור מושבת, דילוג בגרירה מעורבת, ‏incompatible | U2 | `core/catalog.py` | unit (טבלת מקרים) |
| 8 משבצות קבועות, ‏More, ‏plugins רק בקשת More | U2/U3 | `catalog` + `discovery` (slot מכובד רק למניפסט שנמצא בתיקיית `builtin/`) | unit, כולל plugin צד שלישי שמתחזה ל-builtin (id ו-slot) → נשאר בקשת More |
| גלגלת דביקה, ביטול בטבעת, יציאה מהטבעת סוגרת, Shift חדש פותח שוב | U1 | `core/gesture.py` + `wheel_session.py` | unit: טבלת מעברים |
| חימוש אחרי 12px | U7 | `core/wheel_session.py` | unit |
| הצמדה לפי הדיסקית, קשת More מסתובבת פנימה | שלב 3 §2.1 | `core/geometry.py` | unit |
| **רצפת alpha ≥ 1,** בלי שקיפות של כל החלון | C2/C3 | `ui/wheel/renderer.py` + `animator.py` | **qt: רינדור offscreen ל-QImage, כולל פריימים באמצע fade. alpha ≥ 1 בדיסקית ובטבעת, 0 מחוץ להן.** |
| ‏`hide()` בסוף כל fade | C3 | `animator.py` | qt: אחרי fade החלון לא גלוי (`isVisible() == False`) |
| חלון יחיד בזמן גרירה, בלי tooltips | C1 | `ui/wheel/window.py` | code review, ובדיקה ש-`QToolTip` לא בשימוש בחבילה |
| שינוי גודל S/M/L רק כשהגלגלת מוסתרת | U4 | `WheelWindow.apply_size` + `controller` | qt |
| בדיקת elevated בעלייה | שלב 2 §3.7 | `app/application.py` + `platform/system.py` | ידני (הפעלה כמנהל) |
| ‏`runasoriginaluser` ב-installer | שלב 2 §3.7 | `packaging/inno/morphwheel.iss` | ידני: רשימת הבדיקות ב-VM נקי |
| ה-GUI לא מייבא קוד של plugin | R5 | `plugins/discovery.py` | unit: ‏plugin עם `import` שזורק שגיאה, ו-discovery עובר בלי לגעת בו |
| אנימציות כבויות: משך 0 | C7 | `animator.py` + `platform/system.py` | qt |
| השהיה מה-tray: מתעלמים מגרירות, וה-poller עוצר | שלב 2 §3.1 | `app/controller.py` | qt/unit (‏controller עם monitor מדומה) |
| בחירת המקש (D8) מגיעה ל-`ModifierPoller.set_key` מיד | D8 | `controller` + `settings/store.py` | qt |
| ה-hub חוזר על היעד שמתחת לסמן | C5 | `renderer.py` + `SessionView` | qt: רינדור מצב hover |
| הסתרה מיידית כשמשחררים בלי drop | שלב 2 §3.2 | `GestureMachine` (`PointerUp`) + `animator` | unit + qt |
| מצב ממתין: spinner אחרי 150ms, ו-"Can't read this drag" אחרי 1.5s | שלב 3 §4 | `wheel_session.py` (טיימרים כנתון) + `renderer` | unit |

---

## 7. אסטרטגיית בדיקות ו-CI

- **CI** ‏(GitHub Actions, ‏`windows-latest`) בכל push:
  - `ruff check`, ‏`ruff format --check`
  - `mypy` (strict על `core` ועל `plugins.api`)
  - `lint-imports`
  - `pytest`: ‏unit, ‏qt (‏`QT_QPA_PLATFORM=offscreen`) ו-integration
- **גרירות אמיתיות לא רצות ב-CI,** כי הן דורשות סשן אינטראקטיבי פעיל (ראו spike, §7.5). הן נשארות ב-`docs/testing/integration-checklist.md`, ורצות ידנית בסוף כל sprint. `tools/drag_probe.py` נותן להן לוג תזמונים.
- **כלים** (גרסאות נוכחיות ב-PyPI ✅):

  | כלי | גרסה |
  |---|---|
  | pytest | 9.1.1 |
  | pytest-qt | 4.5.0 |
  | ruff | 0.17.1 |
  | mypy | 2.4.0 |
  | import-linter | 2.15 |
  | hatchling | 1.32.4 |
  | tomli-w | 1.2.0 |

- **תלויות runtime:**

  | חבילה | גרסה | הערה |
  |---|---|---|
  | PySide6-Essentials | 6.12.0 | כולל QtSvg ו-QtNetwork (QLocalServer) ✅ |
  | Pillow | 13.0.0 | ‏AVIF מובנה ✅ |
  | pillow-heif | 1.8.1 | ⚠️ ה-wheels כוללים x265 (GPLv2). ראו A6. |
  | platformdirs | 4.13.4 | |
  | tomli-w | 1.2.0 | |

## 8. אריזה והפצה

1. **PyInstaller onedir:**
   - בלי UPX, עם version resource ואייקון.
   - ה-plugin המובנה נכלל כ-data.
   - `freeze_support()` ב-`__main__`.
2. **Inno Setup:**
   - `PrivilegesRequired=lowest`, התקנה ל-`{localappdata}\Programs`.
   - "Launch" עם `runasoriginaluser`.
   - checkbox להפעלה עם Windows.
   - הסרה מוחקת את מפתח ה-Run. הגדרות ו-plugins נשמרים, אלא אם המשתמש בוחר למחוק.
3. **חתימה:** ‏`release.yml` בונה ושולח ל-SignPath (אחרי שיאושר). ה-installer וה-exe חתומים.
4. **פרסום:** ‏GitHub Release, ו-PR ל-`winget-pkgs` (פעולה שלך).

---

## 9. תוכנית sprints

**כללים:**
- כל sprint נגמר ב**נקודת אישור**: דמו או תוצאות בדיקות, ועדכון של רשימת הבדיקות הידנית.
- **רשימת הקבצים בכל sprint היא הסדר שבו הם ייכתבו ב-Phase 5.**
- הגדלים יחסיים (S/M/L). תאריכים: ראו A3.
- 👤 = פעולה שלך. לא אבצע אותה בעצמי, כי היא חיצונית או דורשת את החשבון שלך.

| Sprint | מיילסטון | גודל | מטרה |
|---|---|---|---|
| S0 | M0 | M | תשתית, CI, מעקה הבטיחות הראשון, והבדיקות שנדחו |
| S1 | M1 | M | ליבה טהורה: כל כללי ההתנהגות כקוד נבדק |
| S2 | M1 | M | ‏OS hooks וגלגלת פיתוח: גרירה מ-Explorer מציגה גלגלת חיה |
| S3 | M1 | L | מנוע ההמרה וה-plugin המובנה: המרה מלאה מקצה לקצה |
| S4 | M2 | L | הגלגלת הסופית לפי שלב 3 |
| S5 | M2 | L | ‏toasts, ‏Undo, ‏tray, הגדרות, ‏onboarding ודיאלוגים |
| S6 | M3 | M | מערכת הרחבות לצד שלישי |
| S7 | M4 | M | אריזה, חתימה ושחרור v0.1 |

### S0: ‏Foundation ‏(M0)

**קבצים, לפי הסדר:**
1. `pyproject.toml`
2. `.gitignore`, ‏`LICENSE` (MIT), ‏`README.md` (שלד), ‏`SECURITY.md`, ‏`PRIVACY.md` (טיוטה)
3. `src/morphwheel/__init__.py`, ‏`__main__.py`
4. `logs.py`
5. `settings/paths.py`
6. **`ui/wheel/drop_guard.py`** ו-`tests/unit/test_drop_guard.py` (מטריצה מלאה)
7. `tests/conftest.py`
8. `.github/workflows/ci.yml`
9. `packaging/pyinstaller/morphwheel.spec` (build "hello" עם Raw Input)
10. `tools/drag_probe.py`
11. `docs/testing/integration-checklist.md`

**פעולות שלך 👤:**
- יצירת org או repo ב-GitHub, והפיכתו לציבורי (A1)
- הגשת בקשה ל-SignPath
- רשות: העלאת ה-build ל-VirusTotal. זה שולח קובץ לצד שלישי, ולכן ההחלטה שלך.

**תנאי יציאה:**
- CI ירוק.
- מטריצת `force_copy` עוברת.
- נמדדו: זמן העלייה של worker בגרסה הארוזה, זיכרון במנוחה, וגודל ה-build. מהם ייקבעו היעדים לקריטריונים 5–6 של שלב 2.
- רשימת הבדיקות v1 בוצעה:
  - בדיקות 4–6 מה-spike
  - Esc
  - חלון elevated בחזית
  - ריבוי מסכים, אם זמין
  - **חזרה על מדידות התזמון בסשן קונסולה מקומי (לא RDP)**
  - סריקת Defender
- **ביקורת רישוי של ה-build הארוז:** טקסטי LGPL של Qt, הספריות ש-Pillow מביא איתו, ו-pillow-heif או החלופה שנבחרה ב-A6.
- הבקשה ל-SignPath הוגשה.

### S1: ליבה טהורה ‏(M1)

**קבצים, לפי הסדר:**
1. `core/errors.py`
2. `core/formats.py`
3. `core/jobs.py`
4. `core/geometry.py`
5. `core/catalog.py`
6. `core/output_policy.py`
7. `core/gesture.py`
8. `core/wheel_session.py`

לכל קובץ יש קובץ unit test מקביל, עם טבלאות מעברים.

**תנאי יציאה:** כל השורות בטבלת המעקב שהרכיב שלהן ב-`core` מסומנות "נבדק". ‏import-linter עובר.

### S2: ‏OS hooks וגלגלת פיתוח ‏(M1)

**קבצים, לפי הסדר:**
1. `platform/_win32.py`
2. `platform/system.py`
3. `platform/window_probe.py`
4. `platform/raw_input.py`
5. `platform/modifier_poller.py`
6. `ui/wheel/window.py`, עם renderer בסיסי
7. `app/controller.py` (חלקי)
8. `app/application.py`

**תנאי יציאה:**
- נבדקה ההיתכנות של "Restart normally" מחלון elevated (שלב 3 §6.4).
- Shift+גרירה מ-Explorer מציגה גלגלת פיתוח עם תוכנית משבצות אמיתית.
- ‏drop יוצר `DropRequest` בלוג.
- תזמונים: הגלגלת מופיעה תוך ≤ 50ms, ו-DragEnter מגיע תוך ≤ 100ms ב-p95 (קריטריון 2).

### S3: מנוע ההמרה וה-plugin המובנה ‏(M1)

**קבצים, לפי הסדר:**
1. `plugins/api.py`
2. `plugins/manifest.py`
3. `engine/integrity.py`
4. `engine/file_ops.py`
5. `plugins/loader.py`
6. `builtin/pillow_images/plugin.toml`
7. `builtin/pillow_images/converter.py`
8. `engine/worker_main.py`
9. `engine/worker_pool.py`
10. `engine/dispatcher.py`
11. `platform/shell.py`
12. `engine/undo.py`
13. toast מינימלי (טקסט בלבד)
14. fixtures ו-integration tests

**תנאי יציאה:** ‏M1 גמור.
- קריטריונים 1–4 של שלב 2 עוברים.
- נקבע יעד לזמן ההמרה (קריטריון 4).
- בדיקת ה-plugin ה"זדוני" מובילה להתראה.
- **הוגדר מה Compress עושה ל-PNG,** ו**אומתו ערכי ברירת המחדל** (90/85/70, ‏2048px/80) מול גודל ואיכות (שלב 3 §2.2, §6.2).

### S4: הגלגלת הסופית ‏(M2)

**קבצים, לפי הסדר:**
1. `ui/theme.py`
2. `ui/wheel/renderer.py`
3. `ui/wheel/animator.py`
4. `ui/wheel/window.py` (גרסה סופית)
5. בדיקות qt: רצפת alpha ו-hide

**תנאי יציאה:**
- כל המצבים ב-§3 של שלב 3 עובדים.
- בדיקות M2 מספר 1, 2, 3, 6 ו-9 בוצעו.

### S5: ‏UI מסביב ‏(M2)

**קבצים, לפי הסדר:**
1. `settings/model.py`, ‏`settings/store.py`
2. `ui/toasts/*`
3. `ui/tray.py`
4. `ui/settings_window.py`
5. `ui/onboarding.py`
6. `ui/dialogs.py`
7. `platform/autostart.py`, ‏`platform/single_instance.py`
8. `i18n/`

**תנאי יציאה:**
- ‏M2 גמור.
- בדיקות M2 מספר 4, 5, 7 ו-8 בוצעו.
- זרימת ההפעלה הראשונה עובדת.

### S6: מערכת הרחבות ‏(M3)

**קבצים, לפי הסדר:**
1. `plugins/discovery.py`
2. `plugins/registry.py`
3. עמוד Plugins בהגדרות, ודיאלוג האמון
4. סקופינג של `sys.path` ב-loader
5. `examples/sample_plugin/`
6. `docs/plugins.md`
7. בדיקות קריסה ו-timeout

**תנאי יציאה:**
- ‏M3 גמור: ‏plugin לדוגמה מופיע בקשת More וממיר בלי לשנות את הקוד של האפליקציה (קריטריון 7).
- ‏plugin שקורס לא מפיל את האפליקציה.

### S7: ‏Release v0.1 ‏(M4)

**קבצים, לפי הסדר:**
1. `morphwheel.spec` (גרסה סופית)
2. `packaging/inno/morphwheel.iss`
3. `.github/workflows/release.yml`
4. `packaging/winget/*`
5. `README.md`, ‏`PRIVACY.md`, ‏`SECURITY.md`, ‏`CHANGELOG.md`, ‏**`THIRD_PARTY_NOTICES.md`**
6. `docs/architecture.md`

**פעולות שלך 👤:**
- הגדרת SignPath
- פרסום ה-Release
- PR ל-winget

**תנאי יציאה:**
- ‏M4 גמור: ‏installer חתום פורסם.
- רשימת הבדיקות המלאה עברה ב-VM נקי.

---

## 10. סיכונים ברמת הארכיטקטורה

| סיכון | השפעה | צעד |
|---|---|---|
| עלייה איטית של worker בגרסה הארוזה 🔶 | ההמרה הראשונה מורגשת איטית | מחממים את ה-workers בעלייה; נמדד ב-S0 |
| `freeze_support` ו-spawn בגרסה הארוזה 🔶 | workers לא עולים | ‏build "hello" ב-S0 |
| ‏SignPath לא מאשר בזמן | ‏v0.1 יוצא בלי חתימה | הבקשה נשלחת ב-S0. ההחלטה תחזור אליך ב-S7. |
| false positives באנטי-וירוס | אזהרות בהורדה | onedir, בלי UPX, חתימה, וסריקה ב-S0 |
| תזמונים שונים בסשן מקומי ובסשן RDP | הקריטריונים נמדדו רק ב-RDP | מדידה חוזרת ב-S0 |
| זיכרון: GUI ו-2 workers 🔶 | צריכת זיכרון במנוחה | מדידה ב-S0; גודל ה-pool ניתן לשינוי |

---

## 11. החלטות שנדרשות ממך

| # | החלטה | אפשרויות | ההמלצה שלי | המחיר |
|---|---|---|---|---|
| **A1** | ה-repo | איפה ה-root · מי הבעלים ב-GitHub · מתי ציבורי | **ה-root הוא התיקייה הזו, ושמה נשאר כמו שהוא.** הבעלים: org בשם **`morphwheel`** (היה פנוי בבדיקה). **ציבורי כבר מ-S0.** | הקוד גלוי מההתחלה. ‏SignPath דורשים repo ציבורי, וכל דחייה מאחרת את החתימה. אם תשנה את שם התיקייה, הזיכרון שלי על הפרויקט (שקשור לנתיב) יצטרך העברה. |
| **A2** | תדירות האישורים ב-Phase 5 | (א) לכל sprint · (ב) לכל קובץ | **(א).** אני כותב קובץ אחר קובץ ומדווח על כל קובץ בקצרה. עוצרים לאישור בסוף כל sprint, עם תוצאות בדיקות. | פחות נקודות עצירה ממה שכתוב ב-brief. אם תעדיף, (ב) אפשרי. |
| **A3** | קצב ה-sprints | (א) sprint נגמר כשתנאי היציאה מתקיימים · (ב) time-box שבועי | **(א).** אין לי בסיס להעריך משכי זמן, ועדיף שלא אמציא תאריכים. | אין לוח זמנים קלנדרי |
| **A4** | תלויות של plugins ב-v0.1 | (א) stdlib, מה שכבר ארוז באפליקציה (Pillow ו-pillow-heif), וקוד Python טהור שה-plugin מביא בתיקייה שלו · (ב) התקנה מ-pip | **(א).** אפליקציה ארוזה לא יכולה להריץ pip, ו-native extensions שלא ארוזים לא ייטענו. | ‏plugin שצריך ספרייה עם native code ימתין לגרסה עתידית |
| **A5** | מודל ה-workers | (א) pool קבוע של 2 תהליכים (spawn) עם supervisor · (ב) תהליך לכל משימה · (ג) threads | **(א).** עלייה מהירה, בידוד מקריסות, ובלי לחץ על ה-GIL של ה-GUI. | 2 תהליכי Python נשארים בזיכרון 🔶 (יימדד ב-S0) |
| **A6** | **רישוי HEIC (ממצא חדש)** | (א) לארוז את pillow-heif ב-installer · (ב) תמיכה ב-HEIC כהורדה ב-opt-in מ-PyPI (pillow-heif, גרסה מקובעת עם hash), מה-installer או מההגדרות · (ג) לבנות בעצמנו libheif לפענוח בלבד (LGPL) · (ד) pi-heif | **(ב).** פירוט מתחת לטבלה. | משתמשי HEIC צריכים צעד אחד נוסף (checkbox ב-installer). צריך לבנות מנגנון הורדה, אבל אותו מנגנון ישמש את FFmpeg ב-v0.2. |

**A6, פירוט** (מקורות: [LICENSES_bundled.txt](https://github.com/bigcat88/pillow_heif/blob/master/LICENSES_bundled.txt), [README של pillow-heif](https://github.com/bigcat88/pillow_heif/blob/master/README.md), ‏PyPI ✅):

- **מה מצאתי:**
  - לפי pillow-heif עצמו: *"License for pillow-heif binary wheels: GPLv2, due to base library licenses"*.
  - הסיבה: ה-wheels כוללים x265 (encoder, ‏GPLv2), לצד libheif ו-libde265 (‏LGPLv3).
  - ב-MVP אנחנו רק **קוראים** HEIC, אז ה-encoder לא נחוץ בכלל.
- **(א) לארוז:** ה-installer הופך לחבילה שכוללת קוד GPL.
  - קוד המקור שלנו נשאר MIT.
  - **לא אימתתי** שהשילוב של x265 עם PySide6 (‏LGPLv3) בחבילה אחת תקין מבחינת רישוי. זה תלוי, בין השאר, בשאלה אם x265 הוא GPLv2 בלבד או "or later" 🔶.
  - זה לא ייעוץ משפטי.
- **(ב) הורדה ב-opt-in:**
  - ה-installer שלנו נשאר MIT + LGPL.
  - המשתמש מוריד את pillow-heif מ-PyPI בבקשתו. זה תואם לעיקרון 3 בשלב 2: רשת רק להורדת מנוע, ורק בהסכמה.
  - בגלל זה נוספים קבצים ל-S3:
    - `engine/engines.py` (הורדה, אימות hash, חילוץ ל-`%LOCALAPPDATA%\Morphwheel\engines\`)
    - שורת "HEIC support" בהגדרות
    - checkbox ב-Inno Setup
  - **אם אין תמיכה ב-HEIC:** הגלגלת מראה ב-hub "HEIC support not installed", וה-toast מציע להתקין. 🔶 צריך לבדוק שה-wheel `cp312-win_amd64` נטען מתוך האפליקציה הארוזה (S0).
- **(ג) לבנות בעצמנו:** פתרון נקי, אבל דורש toolchain של C ב-CI, ואחריות על עדכוני אבטחה של libheif.
- **(ד) pi-heif:** ‏**נפסל.** לפי ה-README של pillow-heif, הוא הופסק בגרסה 1.4.0, וכולל libheif עם פגיעות heap overflow בפענוח קובץ זדוני (CVE-2026-84383). הפרטים מגיעים מה-README ולא אומתו בנפרד.

**אחרי האישור:** ‏Phase 5 מתחיל ב-S0, קובץ 1 (`pyproject.toml`). בכל המסמכים הקודמים לא נכתב קוד.

---

## 12. החלטות שאושרו (19.10.2026)

| # | החלטה |
|---|---|
| A1 | ה-repo root הוא התיקייה הזו (השם נשאר). ה-org ב-GitHub: `morphwheel`. ציבורי מ-S0. *(יצירה ופרסום: פעולה של Yuval)* |
| A2 | כותבים קובץ אחר קובץ, עם דיווח על כל קובץ. **עוצרים לאישור בסוף כל sprint.** |
| A3 | sprint נגמר כשתנאי היציאה שלו מתקיימים. בלי תאריכים. |
| A4 | תלויות של plugins: ‏stdlib, מה שכבר ארוז באפליקציה, וקוד Python טהור בתיקיית ה-plugin. בלי pip. |
| A5 | ‏pool קבוע של 2 תהליכי worker (spawn) עם supervisor |
| A6 | **תמיכה ב-HEIC כהורדה ב-opt-in מ-PyPI** (pillow-heif בגרסה מקובעת עם hash). ‏pillow-heif לא נארז ב-installer. *(משנה את היקף ה-MVP משלב 2: HEIC לא מגיע מובנה)* |
