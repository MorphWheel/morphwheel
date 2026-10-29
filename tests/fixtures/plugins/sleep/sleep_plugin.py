"""Never finishes within the task timeout."""

from __future__ import annotations

import time

from morphwheel.plugins.api import ConversionContext


class Converter:
    def convert(self, ctx: ConversionContext) -> None:
        ctx.output_path.write_bytes(b"partial")
        time.sleep(600)
