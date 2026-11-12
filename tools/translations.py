"""Translation catalogs (D3): refresh the ``.ts`` sources and compile the ``.qm`` files.

    python tools/translations.py update he      # -> i18n/translations/morphwheel_he.ts
    python tools/translations.py release        # every .ts there -> .qm beside it (build output)
    python tools/translations.py check          # every ui string is one the extractor reads

The binaries are PySide6's own (``lupdate.exe`` and ``lrelease.exe`` in the package folder). The
extractor runs from the repo root with relative paths, so a ``.ts`` never carries this machine's
path. ``check`` walks the ``ui`` package's AST for every call shape ``lupdate`` reads
(``translate("Ctx", "text"[, None, n])``, ``QT_TRANSLATE_NOOP("Ctx", "text")``, ``self.tr("text"
[, "", n])``) and refuses what ``lupdate`` would lose or get wrong (a name or an f-string as the
text, a keyword ``n`` without the ``None``, ``.tr`` on anything but ``self``) and a literal sent
through any other ``translate`` (``lupdate`` reads it, but it skips the English ``(s)`` rule of
``i18n.translate``). ``update`` runs ``check`` first. The release build runs ``release`` before
PyInstaller (S7).
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from morphwheel.i18n import CATALOG

REPO = Path(__file__).resolve().parents[1]
SOURCES = (Path("src/morphwheel/ui"),)  # relative to the repo root: the only strings a user sees
TRANSLATIONS = Path("src/morphwheel/i18n/translations")
SOURCE_LANGUAGE = "en"

Message = tuple[str, str, bool]  # context, source text, plural


def qt_tool(name: str) -> Path:
    """``lupdate`` or ``lrelease`` from the PySide6 package (the pyside6-* scripts wrap these)."""
    import PySide6

    tool = Path(PySide6.__file__).parent / f"{name}.exe"
    if not tool.exists():
        raise FileNotFoundError(f"{tool} (PySide6's {name} isn't installed)")
    return tool


def _run_tool(name: str, args: list[str], *, cwd: Path | None = None) -> None:
    command = [str(qt_tool(name)), *args]
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{name} failed ({done.returncode}): {done.stderr.strip()}")


def python_files(sources: tuple[Path, ...], cwd: Path) -> list[Path]:
    """Relative paths, sorted: lupdate takes files, not folders, for Python."""
    found: list[Path] = []
    for source in sources:
        found.extend(p.relative_to(cwd) for p in (cwd / source).rglob("*.py"))
    return sorted(found)


# --------------------------------------------------------------------------- the AST side
@dataclass
class Scan:
    messages: set[Message] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)  # "file:line: what lupdate would do"


class _Walker(ast.NodeVisitor):
    def __init__(self, path: Path, scan: Scan) -> None:
        self._path = path
        self._scan = scan
        self._classes: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._classes.append(node.name)
        self.generic_visit(node)
        self._classes.pop()

    def visit_Call(self, node: ast.Call) -> None:
        args = node.args
        keyword_n = any(k.arg == "n" for k in node.keywords)
        literal_text = len(args) >= 2 and isinstance(args[1], ast.Constant)
        match ast.unparse(node.func):
            case "translate":
                self._message(node, 0, 1, plural=keyword_n or len(args) >= 4)
                if keyword_n and len(args) < 3:
                    self._problem(node, "a keyword n needs a positional None before it")
            case "QT_TRANSLATE_NOOP":
                self._message(node, 0, 1, plural=False)
            case "self.tr" if self._classes:
                self._message(node, None, 0, plural=keyword_n or len(args) >= 3)
            case callee if callee.endswith(".tr"):
                self._problem(node, ".tr on anything but self: the context would be the receiver")
            case callee if callee.endswith(".translate") and literal_text:
                self._problem(
                    node, f"{callee} with a literal: only translate() applies the (s) rule"
                )
        self.generic_visit(node)

    def _message(
        self, node: ast.Call, context_at: int | None, text_at: int, *, plural: bool
    ) -> None:
        context = self._classes[-1] if context_at is None else self._literal(node, context_at)
        text = self._literal(node, text_at)
        if context is not None and text is not None:
            self._scan.messages.add((context, text, plural))

    def _literal(self, node: ast.Call, index: int) -> str | None:
        if index >= len(node.args):
            self._problem(node, "too few arguments")
            return None
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        kind = {ast.JoinedStr: "an f-string", ast.BinOp: "a concatenation"}.get(type(arg), "a name")
        self._problem(node, f"{kind} where lupdate needs a literal")
        return None

    def _problem(self, node: ast.AST, what: str) -> None:
        self._scan.problems.append(f"{self._path.as_posix()}:{node.lineno}: {what}")


def scan(sources: tuple[Path, ...] = SOURCES, *, cwd: Path = REPO) -> Scan:
    """Every translatable call in ``sources`` as the extractor would read it, plus the ones it
    wouldn't."""
    result = Scan()
    for path in python_files(sources, cwd):
        tree = ast.parse((cwd / path).read_text(encoding="utf-8"), filename=str(path))
        _Walker(path, result).visit(tree)
    return result


# ----------------------------------------------------------------------- the lupdate side
def lupdate(ts: Path, target_language: str, sources: tuple[Path, ...], *, cwd: Path) -> None:
    files = [str(p) for p in python_files(sources, cwd)]
    options = ["-source-language", SOURCE_LANGUAGE, "-target-language", target_language]
    _run_tool("lupdate", [*files, *options, "-ts", str(ts)], cwd=cwd)


def read_ts(ts: Path) -> set[Message]:
    messages: set[Message] = set()
    for context in ET.parse(ts).getroot().iter("context"):
        name = context.findtext("name") or ""
        for message in context.iter("message"):
            source = message.findtext("source") or ""
            messages.add((name, source, message.get("numerus") == "yes"))
    return messages


def extract(sources: tuple[Path, ...] = SOURCES, *, cwd: Path = REPO) -> set[Message]:
    """What lupdate extracts from ``sources``, through a throwaway ``.ts``."""
    with tempfile.TemporaryDirectory() as tmp:
        ts = Path(tmp) / "extract.ts"
        lupdate(ts, "xx", sources, cwd=cwd)
        return read_ts(ts)


def update(tag: str, *, cwd: Path = REPO) -> Path:
    """Refresh (or start) ``morphwheel_<tag>.ts`` from the sources. Refuses unreadable calls."""
    found = scan(cwd=cwd)
    if found.problems:
        raise SystemExit("\n".join(["strings lupdate would lose:", *found.problems]))
    folder = cwd / TRANSLATIONS
    folder.mkdir(parents=True, exist_ok=True)
    ts = folder / f"{CATALOG}_{tag.replace('-', '_')}.ts"
    lupdate(ts.relative_to(cwd), tag, SOURCES, cwd=cwd)
    return ts


def release(folder: Path = REPO / TRANSLATIONS) -> list[Path]:
    """Compile every ``.ts`` in ``folder`` to a ``.qm`` beside it."""
    compiled: list[Path] = []
    for ts in sorted(folder.glob("*.ts")):
        qm = ts.with_suffix(".qm")
        _run_tool("lrelease", [str(ts), "-qm", str(qm)])
        compiled.append(qm)
    return compiled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Morphwheel translation catalogs")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update", help="refresh the .ts for a language (lupdate)")
    up.add_argument("tags", nargs="+", help="BCP-47 tags, e.g. he")
    sub.add_parser("release", help="compile every .ts into a .qm (lrelease)")
    sub.add_parser("check", help="every ui string is one lupdate reads")
    args = parser.parse_args(argv)
    if args.command == "check":
        found = scan()
        for problem in found.problems:
            print(problem)
        print(f"{len(found.messages)} strings, {len(found.problems)} problems")
        return 1 if found.problems else 0
    if args.command == "update":
        for tag in args.tags:
            print("updated", update(tag))
        return 0
    for qm in release():
        print("compiled", qm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
