# Translating Morphwheel

Morphwheel ships in English and carries the translation infrastructure from day one (D3). Hebrew is
the first language planned after launch (D3a). This page is for whoever adds a language.

## How a language gets in

1. **Extract the strings.** From the repo root:

   ```
   .venv\Scripts\python.exe tools\translations.py update he
   ```

   This writes (or refreshes) `src/morphwheel/i18n/translations/morphwheel_he.ts` with Qt's `lupdate`,
   keeping any translation already there. The file carries no machine path, so it can be committed.

2. **Translate** the `.ts` in Qt Linguist (`.venv\Scripts\pyside6-linguist.exe`) or any editor. Plural
   entries have one form per Hebrew plural form; `%n` is the count, `%1` and `%2` are the caller's
   substitutions, in any order the language needs.

3. **Compile** before a build or a run that should show the language:

   ```
   .venv\Scripts\python.exe tools\translations.py release
   ```

   Every `.ts` in the folder becomes a `.qm` beside it. The `.qm` files are build output (ignored by
   git); the release build runs this step before PyInstaller, which bundles whatever `.qm` files exist.

4. **Try it.** Set `language = "he"` in `settings.toml` (there is no picker in v0.1) and start the app.
   With no setting, Windows' display language decides: the first language in Windows' list that has a
   catalog wins, and English (the source) needs none, so an English Windows that merely lists Hebrew
   second stays English.

## What a translator sees

- **Contexts** are the surfaces: `Toast`, `Tray`, `Settings`, `Dialogs`, `Onboarding`, `Keys`, and
  `WheelWindow` for the wheel's own hub texts.
- **Direction.** When a right-to-left catalog is in effect, the settings window, the toasts, the
  dialogs and the tray menu mirror. The wheel never mirrors: the slots stay where they are (D3a, U2).
  Qt's own strings (the standard buttons) come from Qt's `qtbase` catalog in the same language.
- **English plurals.** The source texts write `%n file(s)`; English resolves `(s)` itself and ships
  without a catalog. A translation replaces the whole text, so the `(s)` never reaches another
  language.

## Rules for the code

Every string a user can see goes through one call, in one shape, because that is what `lupdate`
reads:

```python
translate("Toast", "Converted to %1")                 # a literal context and a literal text
translate("Toast", "%n file(s) converted", None, n)   # a plural: the None before n is required
QT_TRANSLATE_NOOP("Keys", "Shift")                    # a text kept in a table, looked up later
self.tr("More")                                       # inside a QObject: the class is the context
```

A name or an f-string as the text, a keyword `n` without the `None`, `.tr` on anything but `self`, or
a literal through any other `translate` would be lost, mis-filed or skip the English rule, and
`lupdate` says nothing. `python tools\translations.py check` walks the `ui` package and refuses them;
a test runs the same check and compares it with what `lupdate` actually extracts.
