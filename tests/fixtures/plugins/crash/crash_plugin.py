"""Kills its own process mid-conversion, like a native library segfault would."""

from __future__ import annotations

import os

from morphwheel.plugins.api import ConversionContext


class Converter:
    def convert(self, ctx: ConversionContext) -> None:
        ctx.output_path.write_bytes(b"partial")
        os._exit(3)
