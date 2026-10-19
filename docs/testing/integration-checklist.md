# Integration checklist (manual drag tests)

Real Explorer drags can't run in CI, because they need a live, interactive desktop. This checklist is run
by hand at the end of every sprint, and it grows as features land. Results go into the sprint report
(`docs/sprints/`).

## Before you start

- Use an **active, unlocked desktop session**. Over RDP, the session window must be open and in focus.
- Run the probe from a normal terminal, **not as administrator**:
  - From source: `.venv\Scripts\python.exe tools\drag_probe.py`
  - Frozen build: `packaging\output\dist\drag_probe\drag_probe.exe`. Build it with the command in
    `packaging/pyinstaller/morphwheel.spec`.
- **Only drag throwaway copies.** Make a test folder, for example `C:\Temp\mw-test\`, with a few copied
  images. While Shift is held, Explorer's own default is *Move*. If a test fails before the overlay
  catches the drop, Explorer may move the file.
- Logs go to `%LOCALAPPDATA%\Morphwheel\logs\drag_probe-drag-*.log`. When you're done, say which
  tests you ran; the log holds the evidence.
- The probe needs to see Shift go down **after** the drag starts. Pressing Shift before the click
  range-selects files in Explorer.

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
| C9 | Elevated window | Open PowerShell **as administrator**. Click into it and move or click the mouse. Then do C1 with that window open | Shows whether `down`/`up` lines still appear while the elevated window is in front (record the answer). C1 still passes. | S0 |
| C10 | Multiple monitors *(if available)* | Do C1 on each monitor, including one with different scaling | `SHOW … screen=<that monitor>`, and the overlay is centered on the cursor | S0 |
| C11 | Local console timing | Do C1 and C2 **at the physical machine** (not over RDP) | Compare `ENTER` latency with the RDP numbers (9–51 ms in the spike) | S0 |
| C12 | Frozen build | Do C1 with `drag_probe.exe` | Same as C1 | S0 |

## Automated checks (no desktop needed)

| ID | Check | Since |
|---|---|---|
| A1 | `force_copy` matrix: 126 combinations, never Move (`tests/unit/test_drop_guard.py`) | S0 |
| A2 | `drag_probe.py measure`: frozen cold start, memory, Qt modules in workers | S0 |
| A3 | Defender scan of the frozen build (`MpCmdRun -Scan -ScanType 3`) | S0 |
