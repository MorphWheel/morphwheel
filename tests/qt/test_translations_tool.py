"""``tools/translations.py``: the guard agrees with Qt's ``lupdate`` on the real ``ui`` package,
refuses the shapes ``lupdate`` loses, writes a ``.ts`` without this machine's path, and
``release`` compiles what ``QTranslator`` loads. The ``lupdate`` runs are real (a second each)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTranslator

import translations
from conftest import compile_hebrew


def test_every_ui_string_is_one_lupdate_reads() -> None:
    found = translations.scan()
    assert found.problems == []
    extracted = translations.extract()
    assert ("Tray", "Quit", False) in extracted  # lupdate ran on the real package
    assert ("Tray", "%n problem(s) — click for details", True) in extracted
    assert found.messages == extracted


def mini_package(tmp_path: Path, source: str, package: Path = Path("pkg")) -> tuple[Path, ...]:
    folder = tmp_path / package
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "m.py").write_text(source, encoding="utf-8")
    return (package,)


@pytest.mark.parametrize(
    ("line", "what"),
    [
        ('translate(CTX, "x")', "a name"),
        ('translate("C", f"{CTX}")', "an f-string"),
        ('translate("C", "a" + "b")', "a concatenation"),
        ('translate("C", "x", n=3)', "positional None"),
        ('translate("C")', "too few"),
        ('CTX.tr("x")', "anything but self"),
        ('QCoreApplication.translate("C", "x")', "only translate() applies"),
        ('i18n.translate("C", "x")', "only translate() applies"),
    ],
)
def test_the_guard_refuses_what_lupdate_loses(tmp_path: Path, line: str, what: str) -> None:
    found = translations.scan(mini_package(tmp_path, f"CTX = 'C'\n{line}\n"), cwd=tmp_path)
    assert len(found.problems) == 1, found.problems
    assert found.problems[0].startswith("pkg/m.py:2: ")
    assert what in found.problems[0]


def test_self_tr_and_the_plural_shapes_agree_with_lupdate(tmp_path: Path) -> None:
    source = (
        "class W:\n"
        "    def f(self, n):\n"
        '        return self.tr("%n x", "", n), self.tr("y")\n'
        'a = translate("C", "%n a(s)", None, 2)\n'
        'b = translate("C", "%n b(s)", None, n=2)\n'
        'c = translate("C", "plain", "a comment")\n'
        'd = QT_TRANSLATE_NOOP("K", "mark")\n'
        'e = QCoreApplication.translate("K", d)\n'  # the table lookup: nothing to extract
    )
    sources = mini_package(tmp_path, source)
    found = translations.scan(sources, cwd=tmp_path)
    assert found.problems == []
    assert found.messages == {
        ("W", "%n x", True),
        ("W", "y", False),
        ("C", "%n a(s)", True),
        ("C", "%n b(s)", True),
        ("C", "plain", False),
        ("K", "mark", False),
    }
    assert translations.extract(sources, cwd=tmp_path) == found.messages


def test_update_writes_a_ts_without_this_machines_path(tmp_path: Path) -> None:
    ui = translations.SOURCES[0]
    mini_package(tmp_path, 'a = translate("C", "Hello")\n', ui)
    ts = translations.update("he", cwd=tmp_path)
    assert ts == tmp_path / translations.TRANSLATIONS / "morphwheel_he.ts"
    text = ts.read_text(encoding="utf-8")
    assert 'language="he"' in text
    assert 'sourcelanguage="en"' in text
    assert "<source>Hello</source>" in text
    assert str(tmp_path) not in text
    assert str(tmp_path.resolve()) not in text
    assert 'filename="../../ui/m.py"' in text  # relative to the .ts
    mini_package(tmp_path, 'a = translate(CTX, "Hello")\n', ui)
    with pytest.raises(SystemExit, match="would lose"):
        translations.update("he", cwd=tmp_path)


def test_release_compiles_what_qtranslator_loads(tmp_path: Path) -> None:
    qm = compile_hebrew(tmp_path)
    assert qm == tmp_path / "morphwheel_he.qm"
    translator = QTranslator()
    assert translator.load(str(qm))
    assert translator.translate("Tray", "Quit") == "יציאה"
    assert translator.language() == "he"
