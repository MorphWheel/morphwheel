"""Translations (D3, D3a): one ``translate`` for every string a user can see, and the catalogs.

Rules:

- **One call shape, the one Qt's ``lupdate`` reads.** ``translate("Context", "text")`` with a
  literal context and a literal text; a plural is ``translate("Context", "%n file(s)", None, n)``
  (the ``None`` before ``n`` is what the extractor needs); a table of texts is marked with
  ``QT_TRANSLATE_NOOP`` and looked up with ``QCoreApplication.translate``; ``self.tr`` inside a
  ``QObject`` is fine (its context is the class). A name as the context or the text, a keyword
  ``n`` without the ``None``, or an f-string is lost or wrong in the catalog without a word from
  the extractor, and a literal through anything but this ``translate`` skips the English rule
  below, so a test walks the ``ui`` package and refuses them (``tools/translations.py``).
- **English is the source and ships without a catalog.** Qt substitutes ``%n``; the source
  convention ``(s)`` is resolved here when no translation answered. ``%1`` and ``%2`` are replaced
  by the caller.
- **The language is a setting read at start** (``""``: Windows' display language). There is no
  picker in v0.1 (phase-3 §6.2), and a change takes effect at the next start.
- **The direction follows the language in effect:** right-to-left only when a right-to-left
  catalog loaded, and set on the application explicitly (Qt's own lookup would depend on the
  ``qtbase`` file being there). Settings, toasts and dialogs then mirror; the wheel pins itself
  left-to-right so the slots stay where they are (D3a, U2).
- **Windows' language list is walked by hand.** ``QTranslator.load(QLocale.system(), …)`` takes
  the first tag that has a file, so a Hebrew catalog would win on an English Windows that merely
  lists Hebrew second. The walk here stops at the first English tag: the source language needs no
  file. Qt's own catalog (``qtbase``: the standard buttons) is loaded only when ours did.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QGuiApplication

log = logging.getLogger("morphwheel.i18n")

CATALOG = "morphwheel"  # morphwheel_<tag>.qm, written by tools/translations.py
SOURCE_LANGUAGE = QLocale.Language.English
TRANSLATIONS_DIR = Path(__file__).parent / "translations"  # the tests point it elsewhere
_system_locale = QLocale.system  # Windows' display language and the list behind it (tests stand in)


def translate(context: str, text: str, disambiguation: str | None = None, n: int = -1) -> str:
    """Qt's ``translate`` with the English source rule: ``(s)`` resolves when nothing answered."""
    out = QCoreApplication.translate(context, text, disambiguation, n)
    if n >= 0 and out == text.replace("%n", str(n)):  # untranslated: the English source rules
        out = out.replace("(s)", "" if n == 1 else "s")
    return out


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:  # noqa: N802  (the extractor's name)
    """Mark a text kept in a table; look it up later with ``QCoreApplication.translate``.
    Qt's own marker has no type, and the extractor only knows this name."""
    return text


@dataclass
class Installed:
    """What ``install`` put in place: the language in effect, and the way back for ``stop``."""

    language: str  # a BCP-47 tag; "en" when no catalog loaded
    translators: tuple[QTranslator, ...] = ()

    def remove(self, app: QGuiApplication) -> None:
        """Back to the source language and left-to-right. Idempotent."""
        for translator in self.translators:
            app.removeTranslator(translator)
            translator.deleteLater()
        self.translators = ()
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


def install(app: QGuiApplication, language: str = "") -> Installed:
    """Load the catalog for ``language`` (``""``: Windows') and set the layout direction."""
    translator = _load_catalog(_locale_for(language))
    if translator is None:
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        log.info("language: English (the source), no catalog")
        return Installed("en")
    translator.setParent(app)
    app.installTranslator(translator)
    tag = translator.language()  # the catalog's own, not the tag asked for (he-IL finds he)
    locale = QLocale(tag)
    translators = [translator]
    qt = QTranslator(app)
    if qt.load(locale, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt)  # the standard buttons (Cancel, OK) in the same language
        translators.append(qt)
    else:
        log.debug("language: no qtbase catalog for %s", tag)
    direction = locale.textDirection()
    app.setLayoutDirection(direction)
    log.info(
        "language: %s (%s), %s",
        tag,
        "right-to-left" if direction == Qt.LayoutDirection.RightToLeft else "left-to-right",
        translator.filePath(),
    )
    return Installed(tag, tuple(translators))


def _locale_for(language: str) -> QLocale:
    if language:
        locale = QLocale(language)
        if locale.language() != QLocale.Language.C:
            return locale
        log.warning("language: %r isn't a language tag; using Windows' language", language)
    return _system_locale()


def _load_catalog(locale: QLocale) -> QTranslator | None:
    """The first of ``locale``'s languages with a catalog, unless English comes first."""
    for tag in locale.uiLanguages():
        candidate = QLocale(tag)
        if candidate.language() == SOURCE_LANGUAGE:
            return None
        translator = QTranslator()
        if translator.load(candidate, CATALOG, "_", str(TRANSLATIONS_DIR)):  # he-IL, then he
            return translator
    return None
