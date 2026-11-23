# Changelog

All notable changes to Morphwheel are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow
[PEP 440](https://peps.python.org/pep-0440/) (`0.1.0`, `0.2.0rc1`).

The release workflow turns a version's section into the GitHub Release notes, so a version's
section exists before its tag, headed `## [x.y.z] - Unreleased` until the release date is set.

## [0.1.0] - 2026-11-23

The first release: image conversion from File Explorer, with no app window in the flow.

### Added

- **The wheel.** Start dragging a file in File Explorer or on the Desktop, press Shift, and a
  wheel of eight slots appears around the cursor: JPG, PNG, WebP, AVIF, Compress, PDF, ICO and
  More. Drop the file on a slot and a new file is created beside the original. The wheel stays
  open after Shift is released, a drop in the hub cancels, and moving out past the halo returns
  to a normal drag.
- **Inputs:** JPG, PNG, WebP, AVIF, BMP, TIFF and static GIF, with the EXIF orientation applied.
  HEIC and HEIF as an opt-in download (see *Engines*). Several files can be dropped at once.
- **Compress:** a smaller copy, resized to a 2048 px longest side and re-encoded, kept only
  when it is actually smaller.
- **Toasts** in the bottom-right corner: progress, the result, *Show in folder* and *Undo*. Undo
  sends the file Morphwheel created to the Recycle Bin, and only if it is unchanged since.
- **Tray icon** with *Pause Morphwheel*, *Settings…*, *Open log folder*, *About Morphwheel* and *Quit*.
- **Settings:** the trigger key, the wheel size, quality per format, the Compress preset, *Start
  with Windows*, and the plugin list with its order. The UI language follows Windows, or the
  `language` key in `settings.toml` (no picker yet).
- **Engines:** HEIC support as an opt-in download of the pinned `pillow-heif` wheel from PyPI,
  after a consent dialog, verified by SHA-256, kept in your profile and removable from Settings.
- **Plugins** in Python: a folder with a `plugin.toml` and a converter module under
  `%APPDATA%\Morphwheel\plugins\`, shown in the *More* arc, disabled until you enable them. A
  sample plugin and an author's guide (`docs/plugins.md`) are in the repository.
- **A per-user installer** (Inno Setup): no administrator rights, into
  `%LOCALAPPDATA%\Programs\Morphwheel`, with an optional *Start with Windows* task; the uninstaller
  asks before deleting your settings, plugins and logs.
- **Themes:** light and dark follow Windows, with the system accent color; High Contrast is honored;
  animations follow the Windows *Animation effects* switch (`--motion on` or `off` forces them).
- **Translatable UI**, English first; Hebrew is the first language planned after this release.

### Security

- Every drop is accepted as a **copy**, never a move, so Explorer never deletes the source.
- Outputs are **new files**, created exclusively; nothing is overwritten or modified. Each
  source is fingerprinted before conversion and checked after it.
- Conversions run in **separate worker processes** with a time limit; a crashed or hung worker is
  replaced. Plugin code never runs in the app's own process.
- Morphwheel **refuses to run elevated**, and the installer refuses to install as administrator.
- A drag from a window of **lower integrity** (a sandboxed process) does not open the wheel.

### Known limitations

- One wheel for everything: the slots are fixed, and a slot that does not apply to the dragged
  files is disabled rather than hidden.
- Virtual files (a zip's contents, Outlook attachments) and browser downloads are not drag sources.
- Animated images and multi-page TIFFs are refused rather than flattened.
- Windows 11 is the supported platform; Windows 10 22H2 is best-effort.
- The release is unsigned until the code-signing application is approved; verify the installer
  with `SHA256SUMS.txt` from the release page.

[0.1.0]: https://github.com/MorphWheel/morphwheel/releases/tag/v0.1.0
