"""The "malicious" plugin of phase-4 §6: it modifies the source it was given."""

from __future__ import annotations

import shutil

from morphwheel.plugins.api import ConversionContext


class Converter:
    def convert(self, ctx: ConversionContext) -> None:
        shutil.copyfile(ctx.input_path, ctx.output_path)
        with ctx.input_path.open("ab") as f:
            f.write(b"\x00")
