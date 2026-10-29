"""Bundled plugins. They use the public API in ``plugins.api`` like any third-party plugin.

Their only privilege is a fixed wheel slot, and that comes from being found *here* (phase-4 §4.5):
``plugins.manifest.builtin_manifest`` marks a manifest as builtin by its location, never by its id.
"""
