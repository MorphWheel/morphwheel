"""A Morphwheel converter in about thirty lines: images to BMP.

A converter is a class with one method, ``convert(ctx)``: read ``ctx.input_path``, write
``ctx.output_path``, raise an error from ``morphwheel.plugins.api`` when the input is no good.
A plugin is one module or one package (helpers go inside the package); the plugin id is a safe
name for it. The whole contract is in docs/plugins.md.
"""

from __future__ import annotations

from PIL import Image, ImageOps, UnidentifiedImageError

from morphwheel.plugins.api import (
    ConversionContext,
    UnreadableInputError,
    UnsupportedAnimatedError,
)


class Converter:
    def convert(self, ctx: ConversionContext) -> None:
        try:
            with Image.open(ctx.input_path) as im:
                if getattr(im, "n_frames", 1) > 1:
                    raise UnsupportedAnimatedError("Animated images aren't supported")
                im.load()
                ctx.progress(0.3)
                image = ImageOps.exif_transpose(im) or im  # the camera's orientation, applied
                if image.mode not in ("RGB", "L"):  # BMP has no transparency: white behind
                    rgba = image.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                ctx.progress(0.7)
                image.save(ctx.output_path, format="BMP")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as e:
            raise UnreadableInputError("The file couldn't be read") from e
        ctx.progress(1.0)
