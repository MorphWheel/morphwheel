"""Raises at import time. The GUI never imports it; a worker reports PLUGIN_ERROR."""

raise RuntimeError("this plugin is broken on purpose")
