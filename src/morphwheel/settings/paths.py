"""Where Morphwheel keeps its files (phase-4 §5).

This module only computes paths. It never creates or touches anything on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "Morphwheel"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path  # %APPDATA%\Morphwheel (roams with the user profile)
    settings_file: Path  # …\settings.toml
    plugins_dir: Path  # …\plugins\<plugin-id>\
    data_dir: Path  # %LOCALAPPDATA%\Morphwheel (machine-local)
    logs_dir: Path  # …\logs\
    engines_dir: Path  # …\engines\ (opt-in downloads such as HEIC support, decision A6)


def app_paths(*, roaming_base: Path | None = None, local_base: Path | None = None) -> AppPaths:
    """Return Morphwheel's locations for the current user.

    ``roaming_base`` and ``local_base`` replace the per-user roots. Tests use them to point
    everything at a temporary directory.
    """
    config_dir = (
        roaming_base / APP_NAME
        if roaming_base is not None
        else Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True))
    )
    data_dir = (
        local_base / APP_NAME
        if local_base is not None
        else Path(platformdirs.user_data_dir(APP_NAME, appauthor=False, roaming=False))
    )
    return AppPaths(
        config_dir=config_dir,
        settings_file=config_dir / "settings.toml",
        plugins_dir=config_dir / "plugins",
        data_dir=data_dir,
        logs_dir=data_dir / "logs",
        engines_dir=data_dir / "engines",
    )
