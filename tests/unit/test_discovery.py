"""``plugins.discovery``: the scan of the user's plugins folder, as a table of reasons.

Traceability (phase-4 §6):
- R5, the GUI never imports plugin code: a canary plugin writes a marker when imported, a broken
  one raises; discovery sees both and neither runs (negative control: the loader runs the canary).
- U2/U3, a third-party plugin claiming a slot stays in the More arc; one claiming the builtin's
  id is broken (RD-25).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from morphwheel.plugins import discovery
from morphwheel.plugins.discovery import BUILTIN_IDS, BrokenKind, discover
from morphwheel.plugins.loader import PluginSpec, load_converter
from morphwheel.plugins.manifest import (
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    ManifestError,
    builtin_manifest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"

GOOD = """\
[plugin]
id = "com.example.tiff"
name = "TIFF Example"
version = "1.0"
api = "0.1"
entry = "tiff_example:Converter"

[[targets]]
id = "tiff"
label = "TIFF"
output = "tiff"
accepts = ["jpeg", "png"]
"""

CANARY = """\
from pathlib import Path

Path(__file__).with_name("IMPORTED").write_text("the GUI imported plugin code")


class Converter:
    def convert(self, ctx):
        pass
"""


def plug(root: Path, folder: str, manifest: str | bytes = GOOD, **files: str) -> Path:
    directory = root / folder
    directory.mkdir(parents=True)
    if isinstance(manifest, bytes):
        (directory / MANIFEST_NAME).write_bytes(manifest)
    else:
        (directory / MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def junction(link: Path, target: Path) -> None:
    """A directory junction needs no privilege, unlike ``os.symlink`` on Windows."""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
    )
    if result.returncode != 0:
        pytest.skip("can't create a junction here")


# --------------------------------------------------------------------------- the builtin
def test_builtin_only_when_the_user_folder_is_missing(tmp_path: Path) -> None:
    d = discover(tmp_path / "plugins")
    assert [m.plugin.id for m in d.plugins] == sorted(BUILTIN_IDS)
    assert d.plugins[0].is_builtin
    assert d.plugins[0].targets == builtin_manifest().targets
    assert d.broken == ()
    assert d.user_dir_error is None
    assert d.by_id()["pillow_images"] is d.plugins[0]


def test_a_bundled_directory_that_is_wrong_raises(tmp_path: Path) -> None:
    """A packaging bug, not a user problem: the bundled set must be exactly BUILTIN_IDS."""
    with pytest.raises(FileNotFoundError):
        discover(tmp_path, builtin_dir=tmp_path / "nope")
    (tmp_path / "builtin").mkdir()
    with pytest.raises(ManifestError, match="bundled plugins"):
        discover(tmp_path, builtin_dir=tmp_path / "builtin")
    plug(tmp_path / "builtin", "pillow_images", GOOD.replace("com.example.tiff", "pillow_images"))
    plug(tmp_path / "builtin", "extra", GOOD.replace("com.example.tiff", "extra"))
    with pytest.raises(ManifestError, match="found \\['extra', 'pillow_images'\\]"):
        discover(tmp_path, builtin_dir=tmp_path / "builtin")


# --------------------------------------------------------------------------- R5
def test_user_plugins_are_found_without_importing_any_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = tmp_path / "plugins"
    canary = plug(
        user,
        "test.canary",
        GOOD.replace("com.example.tiff", "test.canary").replace("tiff_example", "canary_plugin"),
        **{"canary_plugin.py": CANARY},
    )
    plug(user, "test.broken", (FIXTURES / "broken" / MANIFEST_NAME).read_text(encoding="utf-8"))
    (user / "test.broken" / "broken_plugin.py").write_bytes(
        (FIXTURES / "broken" / "broken_plugin.py").read_bytes()
    )
    modules_before = set(sys.modules)
    path_before = list(sys.path)

    d = discover(user)

    assert [m.plugin.id for m in d.plugins] == ["pillow_images", "test.broken", "test.canary"]
    assert d.broken == ()
    assert not (canary / "IMPORTED").exists()
    assert not {m for m in set(sys.modules) - modules_before if m.endswith("_plugin")}
    assert sys.path == path_before
    # Negative control: the canary does write its marker when something imports it.
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "canary_plugin", raising=False)
    load_converter(PluginSpec("test.canary", "canary_plugin:Converter", canary))
    assert (canary / "IMPORTED").exists()


# --------------------------------------------------------------------------- the reasons
BINARY = b"\xff\xfe\x00\x01" + b"\x00" * 16
DEEP = "a = " + "[" * 5000 + "]" * 5000
BAD_API = GOOD.replace('api = "0.1"', 'api = "9.0"')
K = BrokenKind


@pytest.mark.parametrize(
    ("folder", "manifest", "kind", "reason", "plugin_id"),
    [
        (
            "wrongname",
            GOOD,
            K.NAME_MISMATCH,
            "the folder must be named com.example.tiff",
            "com.example.tiff",
        ),
        (
            "pillow_images",
            GOOD.replace("com.example.tiff", "pillow_images"),
            K.ID_TAKEN,
            "the id pillow_images is already taken",
            "pillow_images",
        ),
        ("com.example.tiff", "not = toml = at all", K.INVALID, "not valid TOML", None),
        ("com.example.tiff", BAD_API, K.INVALID, "plugin.api: 9.0 is not compatible", None),
        ("com.example.tiff", BINARY, K.INVALID, "plugin.toml: not UTF-8 text", None),
        ("com.example.tiff", DEEP, K.ERROR, "can't read this plugin: RecursionError", None),
        (
            "com.example.tiff",
            GOOD + "#" * MAX_MANIFEST_BYTES,
            K.INVALID,
            "plugin.toml is larger than 64 KiB",
            None,
        ),
    ],
    ids=["name", "builtin-id", "toml", "api", "binary", "deep", "oversized"],
)
def test_broken_plugins_are_reported_with_a_kind_and_a_reason(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    folder: str,
    manifest: str | bytes,
    kind: BrokenKind,
    reason: str,
    plugin_id: str | None,
) -> None:
    user = tmp_path / "plugins"
    directory = plug(user, folder, manifest)
    with caplog.at_level(logging.WARNING, logger="morphwheel.plugins.discovery"):
        d = discover(user)
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]  # never in the usable list
    (b,) = d.broken
    assert b.directory == directory
    assert b.kind is kind
    assert reason in b.reason
    assert b.plugin_id == plugin_id
    assert reason in caplog.text


def test_a_folder_without_a_manifest_and_the_nested_unzip(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    (user / "empty").mkdir(parents=True)
    plug(user / "com.example.tiff", "com.example.tiff")  # unzipped one level too deep
    d = discover(user)
    assert {b.kind for b in d.broken} == {K.NO_MANIFEST}
    reasons = {b.directory.name: b.reason for b in d.broken}
    assert reasons["empty"] == "no plugin.toml in this folder"
    assert reasons["com.example.tiff"].startswith("no plugin.toml in this folder; there is one in")
    assert "move that folder up" in reasons["com.example.tiff"]


def test_a_manifest_that_is_a_directory_is_a_broken_plugin(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    (user / "com.example.tiff" / MANIFEST_NAME).mkdir(parents=True)
    d = discover(user)
    (b,) = d.broken
    assert b.kind is K.INVALID
    assert b.reason.startswith("can't read plugin.toml: ")
    assert b.plugin_id is None


def test_a_slot_claim_from_a_third_party_is_ignored_not_broken(tmp_path: Path) -> None:
    """U2/U3: the plugin is usable and its target has no slot, so it goes to the More arc."""
    user = tmp_path / "plugins"
    plug(user, "com.example.tiff", GOOD + 'slot = "N"\n')
    d = discover(user)
    assert d.broken == ()
    (t,) = d.by_id()["com.example.tiff"].targets
    assert t.id == "com.example.tiff:tiff"
    assert t.slot is None


# --------------------------------------------------------------------------- the folder
def test_ignored_entries_and_a_stray_manifest_at_the_root(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    plug(user, ".hidden")
    plug(user, "__pycache__")
    plug(user, "_private")
    user.joinpath("notes.txt").write_text("not a folder", encoding="utf-8")
    user.joinpath(MANIFEST_NAME).write_text(GOOD, encoding="utf-8")
    d = discover(user)
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]
    (b,) = d.broken
    assert b.directory == user
    assert b.kind is K.MISPLACED
    assert b.reason == "plugin.toml must be inside a folder named after the plugin id"


def test_folders_come_in_name_order_case_insensitively(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    for name in ("b.two", "a.one", "C.three"):
        plug(user, name, GOOD.replace("com.example.tiff", name.lower()))
    d = discover(user)
    assert [m.plugin.id for m in d.plugins] == ["pillow_images", "a.one", "b.two", "c.three"]
    assert d.plugins[3].directory.name == "C.three"  # the folder keeps its spelling


def test_a_junction_is_reported_not_followed(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    target = plug(tmp_path / "elsewhere", "com.example.tiff")
    user.mkdir()
    junction(user / "com.example.tiff", target)
    d = discover(user)
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]
    (b,) = d.broken
    assert b.kind is K.LINK
    assert b.reason == "the folder is a link; copy the plugin here instead"


def test_the_nested_hint_never_looks_through_a_junction(tmp_path: Path) -> None:
    user = tmp_path / "plugins"
    folder = user / "com.example.tiff"
    folder.mkdir(parents=True)
    plug(tmp_path / "elsewhere", "com.example.tiff")
    junction(folder / "com.example.tiff", tmp_path / "elsewhere" / "com.example.tiff")
    d = discover(user)
    (b,) = d.broken
    assert b.reason == "no plugin.toml in this folder"  # the junction is not consulted


def test_a_plugins_folder_that_is_a_link_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    plug(real, "com.example.tiff")
    junction(tmp_path / "plugins", real)
    d = discover(tmp_path / "plugins")
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]
    assert d.user_dir_error == "the plugins folder is a link; it must be a real folder"


def test_a_plugins_path_that_is_a_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "plugins").write_text("not a folder", encoding="utf-8")
    d = discover(tmp_path / "plugins")
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]
    assert d.user_dir_error == "the plugins path is a file; it must be a folder"


def test_a_plugins_folder_that_cannot_be_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = tmp_path / "plugins"
    user.mkdir()
    real_entries = discovery._entries

    def denied(directory: Path) -> list[os.DirEntry[str]]:
        if directory == user:
            raise PermissionError(13, "Access is denied")
        return real_entries(directory)

    monkeypatch.setattr(discovery, "_entries", denied)
    d = discover(user)
    assert [m.plugin.id for m in d.plugins] == ["pillow_images"]
    assert d.user_dir_error == "can't list the plugins folder: Access is denied"
    assert d.broken == ()
