# Privacy

*Draft. It will be finalized for v0.1.*

- **No telemetry.** Morphwheel does not collect or send usage data.
- **No network by default.** Morphwheel connects to the internet only when you explicitly ask it to:
  - **Opt-in engine downloads.** For example, HEIC support downloads the `pillow-heif` package from PyPI
    (pypi.org), at a pinned version, and verifies it by hash.
- **Your files stay local.** Conversions run on your computer. Files are never uploaded.
- **Local logs.** A log file in `%LOCALAPPDATA%\Morphwheel\logs\` records file paths and timings to
  help with debugging. It never leaves your computer unless you choose to share it.
- **Settings** are stored in `%APPDATA%\Morphwheel\settings.toml`.
