# Contributing to Morphwheel

Thank you for helping. Morphwheel is a small, free Windows tool, and bug reports, fixes,
translations, plugins and documentation are all welcome.

## Before you start

- **A bug or an idea:** open an [issue](https://github.com/MorphWheel/morphwheel/issues/new/choose).
  For a question, use [Discussions](https://github.com/MorphWheel/morphwheel/discussions).
- **A security problem**, or anything that changed, moved or deleted one of your files: do **not**
  open a public issue. Report it privately, as described in [`SECURITY.md`](SECURITY.md).
- **A larger change** (a new feature, a new dependency, a change to how the wheel behaves): open an
  issue first, so we can agree on the approach before you spend time on it. Approved decisions are
  listed in [`docs/decisions.md`](docs/decisions.md); a change that reverses one needs a discussion
  first.

## Setting up

Morphwheel needs Windows and Python 3.12.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,heic]"
.venv\Scripts\python.exe -m morphwheel --debug
```

The `heic` extra is for running the HEIC tests locally only (see the safety rules below).
[`docs/architecture.md`](docs/architecture.md) explains how the code is laid out.

## The checks

Every pull request must pass the same checks as CI. Run them before you push:

```powershell
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe
.venv\Scripts\lint-imports.exe
.venv\Scripts\python.exe -m pytest -q
```

Add a test for every behavior you change, and for every bug you fix (a test that fails without
the fix). The Qt tests run offscreen, so they need no display.

## Safety rules

Morphwheel works on people's own files. These rules are not negotiable, and a pull request that
breaks one will not be merged:

- **Every drop is a copy, never a move.** Every drag event on the wheel goes through
  `ui/wheel/drop_guard.force_copy()`. Under Shift, Windows proposes a move, and File Explorer would
  delete the source after the drop.
- **A source file is never modified, moved or overwritten.** Outputs are new files, reserved with
  `engine/file_ops.reserve_unique()`, written to a temporary file and committed.
- **The wheel window:** every pixel that catches a drop keeps an alpha of at least 1; never fade it
  with window opacity; it is hidden at the end of every fade; and it is the only window shown
  during a drag (no tooltips or popups).
- **Import boundaries** (checked by `lint-imports`): `core/` has no Qt, no Win32 and no ctypes;
  worker code never imports Qt; the GUI process never imports plugin code; `plugins/api.py` uses
  the standard library only.
- **No GPL code in the installer.** pillow-heif is GPLv2 and stays an opt-in download. A new
  dependency needs a license that allows bundling, and a line in
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Style

- Formatting and lint are `ruff`; types are `mypy --strict`.
- User-facing text is in English and translatable, and layouts work right-to-left; see
  [`docs/translations.md`](docs/translations.md).
- Commit messages and pull-request titles start with the area, then a short summary in plain
  English, for example `Engine: refuse a source that changed during conversion`.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each pull request to one change, with its tests and any docs it affects.
3. Fill in the pull-request template. CI runs on every pull request (a first-time contributor's run
   waits for a maintainer's approval).
4. A maintainer reviews it. Pull requests are squash-merged, so the title becomes the commit
   message.

## Plugins and translations

- **Plugins** add converters without changing the app: see [`docs/plugins.md`](docs/plugins.md)
  and the example in [`examples/sample_plugin`](examples/sample_plugin). A plugin can live in your
  own repository; it doesn't need to be merged here.
- **Translations:** [`docs/translations.md`](docs/translations.md) walks through adding a language.
  Hebrew is the first one planned.

## License

Morphwheel is released under the [MIT license](LICENSE). By opening a pull request, you agree that
your contribution is released under the same license.

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
