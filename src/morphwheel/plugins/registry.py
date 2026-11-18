"""From what was discovered and the ``plugins`` settings to what the wheel offers (phase-4 §4.6).

The registry is a pure function of a :class:`Discovery` and the :class:`PluginPrefs`: it decides
which third-party plugins are **enabled** (the trust record, phase-2 §3) and in which **order**
their targets fill the More arc (phase-3 §2.3, U3). It never writes the settings: the Plugins page
and the trust prompt do (S6 file 3), and the app rebuilds the registry on every change.

Rules:

- **Trust is the ``enabled`` list.** A third-party plugin is enabled iff its id is listed. The
  builtin plugin is always enabled and never listed; listing it changes nothing. Trust is keyed
  by id, as the prompt runs when the user enables a plugin (phase-3 §6.5): a folder replaced
  under the same id stays enabled (RD-26).
- **One stable order for every third-party plugin,** enabled or not: the ids in ``order`` first,
  then the rest by folder name (the discovery order). The page shows that list and writes it
  back whole; a switch flips ``enabled`` without moving the row. The arc holds the enabled subset's
  targets, each plugin's in manifest order, and the catalog shows the first ``MORE_ARC_MAX``.
- **Ids that match nothing are ignored** and logged once per build: a settings id no discovered
  plugin has (a folder removed, broken, or a string that was never an id; the S5 carry-over is
  closed by construction, since an id is never turned into a path). A repeated id counts once.
- **What the workers may load** is exactly the enabled plugins' specs (``specs``): a worker
  refuses a task whose provider it wasn't configured with, so the gate holds on both sides.
- **One module name per plugin (RD-28).** A worker imports a plugin's entry by its module
  name, so two plugins whose entries share a top-level name would run one plugin's code under
  the other's id, depending on which loaded first. The later one in row order is reported
  broken (``BrokenKind.MODULE_CLASH``) and left out, enabled or not, so the page says so before
  any worker sees it; the loader refuses the same thing as a backstop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from morphwheel.core.catalog import MORE_ARC_MAX, Target
from morphwheel.plugins.discovery import BrokenKind, BrokenPlugin, Discovery
from morphwheel.plugins.loader import PluginSpec, top_module
from morphwheel.plugins.manifest import Manifest
from morphwheel.settings.model import PluginPrefs

log = logging.getLogger("morphwheel.plugins.registry")


@dataclass(frozen=True)
class PluginEntry:
    """One discovered plugin as the Plugins page sees it."""

    manifest: Manifest
    enabled: bool  # the builtin: always

    @property
    def id(self) -> str:
        return self.manifest.plugin.id


@dataclass(frozen=True)
class Registry:
    prefs: PluginPrefs  # what it was built from; the app compares a new value against it
    entries: tuple[PluginEntry, ...]  # the builtin first, then every third-party plugin in order
    broken: tuple[BrokenPlugin, ...]  # from discovery, untouched

    @property
    def third_party(self) -> tuple[PluginEntry, ...]:
        return tuple(e for e in self.entries if not e.manifest.is_builtin)

    @property
    def arc_targets(self) -> tuple[Target, ...]:
        """The enabled third-party targets in arc order (all of them; the catalog cuts at 6)."""
        return tuple(t for e in self.third_party if e.enabled for t in e.manifest.targets)

    @property
    def targets(self) -> tuple[Target, ...]:
        """What the catalog is built from: the builtin's targets, then the arc's."""
        return tuple(t for e in self.entries if e.enabled for t in e.manifest.targets)

    @property
    def more_overflow(self) -> int:
        """Enabled targets the arc can't show (phase-3 §2.3: the settings say how many)."""
        return max(0, len(self.arc_targets) - MORE_ARC_MAX)

    @property
    def specs(self) -> tuple[PluginSpec, ...]:
        """What the workers may load: the builtin (from the package) and the enabled plugins."""
        return tuple(
            PluginSpec(
                e.id,
                e.manifest.plugin.entry,
                None if e.manifest.is_builtin else e.manifest.directory,
            )
            for e in self.entries
            if e.enabled
        )

    def entry(self, plugin_id: str) -> PluginEntry | None:
        return next((e for e in self.entries if e.id == plugin_id), None)


def build_registry(discovery: Discovery, prefs: PluginPrefs) -> Registry:
    known = discovery.by_id()
    enabled = _third_party_ids(prefs.enabled, known)
    ordered = _third_party_ids(prefs.order, known)
    entries = [PluginEntry(m, True) for m in discovery.plugins if m.is_builtin]
    claimed = {top_module(m.plugin.entry): m.plugin.id for m in discovery.plugins if m.is_builtin}
    third_party = [m.plugin.id for m in discovery.plugins if not m.is_builtin]
    rest = [pid for pid in third_party if pid not in ordered]
    rows = ordered + rest
    # Enabled plugins claim their module name first, in row order, then the disabled ones:
    # installing a plugin never breaks one that already works.
    clashes: dict[str, str] = {}  # pid -> the plugin that owns its module name
    for pass_enabled in (True, False):
        for pid in rows:
            if (pid in enabled) is pass_enabled:
                top = top_module(known[pid].plugin.entry)
                if top in claimed:
                    clashes[pid] = claimed[top]
                else:
                    claimed[top] = pid
    entries += [PluginEntry(known[pid], pid in enabled) for pid in rows if pid not in clashes]
    broken = list(discovery.broken)
    for pid, owner in clashes.items():
        top = top_module(known[pid].plugin.entry)
        reason = (
            f"the module name {top!r} is also used by {owner}; rename it "
            f"(the plugin id is a safe name)"
        )
        log.warning("plugins: %s: %s", pid, reason)
        broken.append(BrokenPlugin(known[pid].directory, BrokenKind.MODULE_CLASH, reason, pid))
    return Registry(prefs, tuple(entries), tuple(broken))


def _third_party_ids(ids: tuple[str, ...], known: dict[str, Manifest]) -> list[str]:
    """The ids that name a discovered third-party plugin, once each; the others are logged."""
    kept: list[str] = []
    for pid in ids:
        manifest = known.get(pid)
        if manifest is None:
            log.warning("plugins: settings name %r, which is not an installed plugin; ignored", pid)
        elif not manifest.is_builtin and pid not in kept:
            kept.append(pid)
    return kept
