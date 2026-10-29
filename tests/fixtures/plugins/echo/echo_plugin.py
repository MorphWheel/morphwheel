"""The well-behaved control: copies the input to the output and reports progress."""

from __future__ import annotations

import shutil

from morphwheel.plugins.api import ConversionContext


class Converter:
    def convert(self, ctx: ConversionContext) -> None:
        ctx.progress(0.0)
        shutil.copyfile(ctx.input_path, ctx.output_path)
        ctx.progress(1.0)
