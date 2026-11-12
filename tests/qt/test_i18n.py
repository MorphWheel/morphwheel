"""``i18n``: the English source rule, a right-to-left catalog, Windows' language list, and the way
back. One application serves the whole session, so every install is removed again."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication, QLabel

from morphwheel import i18n
from morphwheel.i18n import Installed, translate

LTR = Qt.LayoutDirection.LeftToRight
RTL = Qt.LayoutDirection.RightToLeft
Install = Callable[[str], Installed]


@pytest.fixture
def install(qapp: QApplication) -> Iterator[Install]:
    """``i18n.install`` on the session's application; whatever it put in place is removed, and
    the application is left-to-right again."""
    done: list[Installed] = []

    def _install(language: str) -> Installed:
        done.append(i18n.install(qapp, language))
        return done[-1]

    yield _install
    for item in done:
        item.remove(qapp)
    assert qapp.layoutDirection() == LTR
    assert translate("Toast", "Undo") == "Undo"


def windows_lists(monkeypatch: pytest.MonkeyPatch, *tags: str) -> None:
    """Stands in for ``QLocale.system()``: only the language list matters to ``install``."""
    stub = SimpleNamespace(uiLanguages=lambda: list(tags))
    monkeypatch.setattr(i18n, "_system_locale", lambda: cast(QLocale, stub))


def test_english_resolves_the_plural_convention_without_a_catalog() -> None:
    assert translate("Toast", "%n file(s) converted", None, 1) == "1 file converted"
    assert translate("Toast", "%n file(s) converted", None, 3) == "3 files converted"
    assert translate("Toast", "%n file(s) converted", None, 0) == "0 files converted"
    assert translate("Toast", "Undo") == "Undo"
    assert translate("Toast", "Undo", "a disambiguation") == "Undo"


@pytest.mark.usefixtures("hebrew")
def test_a_right_to_left_catalog_translates_and_mirrors(
    qapp: QApplication, install: Install
) -> None:
    before = QLabel()
    done = install("he")
    assert done.language == "he"
    assert translate("Toast", "Undo") == "בטל"
    one = translate("Toast", "%n file(s) converted to %1", None, 1)
    assert one.replace("%1", "PNG") == "קובץ אחד הומר ל-PNG"
    assert translate("Toast", "%n file(s) converted to %1", None, 4) == "4 קבצים הומרו ל-%1"
    assert translate("Toast", "%n other(s)", None, 2) == "2 others"  # not in the catalog: English
    assert translate("QPlatformTheme", "Cancel") == "ביטול"  # Qt's own catalog came along
    after = QLabel()
    assert (qapp.layoutDirection(), before.layoutDirection(), after.layoutDirection()) == (
        RTL,
        RTL,
        RTL,
    )
    done.remove(qapp)
    done.remove(qapp)  # idempotent: stop() runs twice in the tests
    assert translate("QPlatformTheme", "Cancel") == "Cancel"
    assert before.layoutDirection() == LTR


@pytest.mark.usefixtures("hebrew")
def test_a_region_finds_its_language_catalog(qapp: QApplication, install: Install) -> None:
    assert install("he-IL").language == "he"  # the file's language, not the tag asked
    assert qapp.layoutDirection() == RTL


def test_without_a_catalog_english_stays_left_to_right(
    qapp: QApplication, install: Install, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(i18n, "TRANSLATIONS_DIR", tmp_path)
    assert install("he").language == "en"
    assert qapp.layoutDirection() == LTR
    assert translate("Toast", "Undo") == "Undo"


@pytest.mark.usefixtures("hebrew")
def test_an_unknown_tag_is_a_warning_and_windows_language(
    install: Install, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    windows_lists(monkeypatch, "he-IL", "en-US")
    with caplog.at_level(logging.WARNING, logger="morphwheel.i18n"):
        done = install("xx-nonsense")
    assert "xx-nonsense" in caplog.text
    assert done.language == "he"  # Windows' first language, as if the setting were empty


@pytest.mark.usefixtures("hebrew")
@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (("en-US", "he-IL"), "en"),  # an English Windows that lists Hebrew second: English
        (("he-IL", "en-US"), "he"),  # a Hebrew Windows: Hebrew
        (("fr-FR", "he-IL"), "he"),  # no French catalog, so the next language with one
        (("fr-FR", "en-US"), "en"),
        (("fr-FR",), "en"),  # nothing with a catalog: the source
    ],
)
def test_windows_language_list_is_walked_until_english(
    qapp: QApplication,
    install: Install,
    monkeypatch: pytest.MonkeyPatch,
    tags: tuple[str, ...],
    expected: str,
) -> None:
    windows_lists(monkeypatch, *tags)
    assert install("").language == expected
    assert qapp.layoutDirection() == (RTL if expected == "he" else LTR)
