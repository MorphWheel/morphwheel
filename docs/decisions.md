# Decision log

Every approved decision, in one place, with a stable ID and a link to where it was argued.
**A new decision is recorded here before it reaches the code.**

Discovery documents (`discovery/`) are the approved specs. They are written in Hebrew and kept as an archive.

| ID | Date | Decision | Source |
|---|---|---|---|
| **P1-1** | 2026-10-19 | **Positioning (A):** an independent project that stands apart through safety first, a configurable trigger, Python plugins and signed builds. Filee and tangerine-windows are reference only. | [Phase 1 §7](discovery/phase-1-research.md#7-החלטות-שאושרו-19102026) |
| **P1-2** | 2026-10-19 | **PySide6 under the MIT license**, instead of PyQt6 | Phase 1 §7 |
| **P1-3** | 2026-10-19 | **Shift is the default trigger** and can be changed. CopyAction is always forced. | Phase 1 §7 |
| **SP-1** | 2026-10-19 | **Detection** uses Raw Input plus polling. No low-level hook, no keyboard hook. | [Spike](discovery/phase-1b-spike-results.md) |
| **SP-2** | 2026-10-19 | **Every drop is forced to Copy** (`force_copy`) | Spike |
| **SP-3** | 2026-10-19 | **The OLE-clipboard detection path is rejected** | Spike §6 |
| **SP-4** | 2026-10-19 | **Manual tests 4–6** (desktop source, Ctrl+C then drag, title-bar drag) are deferred to the S0 checklist | Spike |
| **D1** | 2026-10-19 | **Video and audio (FFmpeg) come in v0.2.** The MVP covers images and PDF. | [Phase 2 §8](discovery/phase-2-concept.md#8-החלטות-שאושרו-19102026) |
| **D2** | 2026-10-19 | **A "Compress" slice.** Its output is `<name> (compressed).<ext>`. | Phase 2 §8 |
| **D3** | 2026-10-19 | **i18n infrastructure from day one**, shipping in English only | Phase 2 §8 |
| **D3a** | 2026-10-19 | **The app is English-native. Hebrew is the first language added after launch.** RTL layout must therefore be planned from the start: settings, toasts and dialogs mirror. The wheel does not, so that slot positions stay fixed (U2). | User, during S0 |
| **D4** | 2026-10-19 | **Windows 11 is official.** Windows 10 22H2 is best-effort. | Phase 2 §8 |
| **D5** | 2026-10-19 | **Limited Undo:** the file goes to the Recycle Bin, only for paths the app created, and only if the file is unchanged since conversion | Phase 2 §8 |
| **D6** | 2026-10-19 | **The project name is Morphwheel.** The user reconfirmed it during S0. | Phase 2 §8 |
| **D7** | 2026-10-19 | **Milestones:** M0 Foundation, M1 core, M2 UI, M3 plugins, M4 release | Phase 2 §8 |
| **D8** | 2026-10-19 | **Selectable trigger keys:** Shift, Ctrl, Ctrl+Shift. No Alt. | Phase 2 §8 |
| **U1** | 2026-10-19 | **The wheel is sticky, and a catch halo cancels a drop.** Leaving the halo returns to a normal drag. Pressing Shift again reopens the wheel. Esc cancels everything. | [Phase 3 §11](discovery/phase-3-ux.md#11-החלטות-שאושרו-19102026) |
| **U2** | 2026-10-19 | **8 fixed slots.** The source format is shown disabled. In a mixed drag, files already in the target format are skipped. | Phase 3 §11 |
| **U3** | 2026-10-19 | **A More slot (NW) opens an outer arc** with up to 6 plugin items | Phase 3 §11 |
| **U4** | 2026-10-19 | **Size M is the default:** disc diameter 236 logical px. S, M and L are available. | Phase 3 §11 |
| **U5** | 2026-10-19 | **No blur in the MVP.** The surface is 92% opaque. | Phase 3 §11 |
| **U6** | 2026-10-19 | **Our own toast**, in the bottom-right corner | Phase 3 §11 |
| **U7** | 2026-10-19 | **Arming:** a slot can be selected only after the pointer has moved 12 px or more | Phase 3 §11 |
| **A1** | 2026-10-19 | **Repo:** this folder is the root and keeps its name. GitHub org `morphwheel`. Public from S0. | [Phase 4 §12](discovery/phase-4-architecture.md#12-החלטות-שאושרו-19102026) |
| **A2** | 2026-10-19 | **Workflow:** files are written one at a time, with a report after each. **Approval stop at the end of every sprint.** | Phase 4 §12 |
| **A3** | 2026-10-19 | **No dates.** A sprint ends when its exit criteria are met. | Phase 4 §12 |
| **A4** | 2026-10-19 | **Plugin dependencies:** the standard library, what is bundled, and pure Python. No pip. | Phase 4 §12 |
| **A5** | 2026-10-19 | **A fixed pool of 2 worker processes** (spawn), with a supervisor | Phase 4 §12 |
| **A6** | 2026-10-19 | **HEIC support is an opt-in download from PyPI.** pillow-heif is never bundled, because its wheels are GPLv2. | Phase 4 §12 |
| **A5a** | 2026-10-19 | **The worker processes run a separate, Qt-free executable** (`morphwheel-worker.exe`, via `multiprocessing.set_executable`). Built in S3. Reason: in the frozen app, PyInstaller's PySide6 runtime hook loads QtCore into every spawned process (S0 Finding 1). | [S0 report](sprints/S0.md) |
| **T5** | 2026-10-19 | **Idle memory targets:** GUI ≤ 70 MB working set; each worker ≤ 35 MB (phase-2 criterion 5) | S0 report |
| **T6** | 2026-10-19 | **Size targets:** installed ≤ 100 MB; installer download ≤ 45 MB (phase-2 criterion 6) | S0 report |
| **S0-1** | 2026-10-19 | **S1 starts while S0's user items stay open** (GitHub repo and CI, checklist C1–C12, SignPath). They must close **before S2**. | User |
| **L1** | 2026-10-19 | **Repo docs and our conversation are in English** from now on. The discovery docs stay in Hebrew as the approved archive. | User, during S0 |
| **RD-1** | 2026-10-19 | **A drop still counts toward arming (U7).** A drop 12 px or more from where the wheel appeared can select the slot under it, even if no DragMove repainted it as selected. Only the More arc is frozen at the drop: it doesn't open or close, so a drop never picks an arc item that wasn't shown (RF-2). | RF-2 fix, `progress.md` |
| **RD-2** | 2026-10-19 | **"Already compact" is not a failure.** A Compress batch where some files came out smaller and the rest were already compact is a success. The toast lists the compact files the way the batch toast lists skipped ones, e.g. "3 compressed · 1 already compact" (extends phase-3 §5). | RF-5 fix, `progress.md` |
| **RD-3** | 2026-10-19 | **Output names cut only a known image extension.** Compress takes the extension from the detected format, and keeps the source's own spelling when it matches (D2). A dot that isn't a known image extension stays in the name: `Dr. Who` (a PNG) → `Dr. Who.jpg` / `Dr. Who (compressed).png`; `notes.txt` that is really a PNG → `notes.txt.jpg`. | RF-3 fix, `progress.md` |
