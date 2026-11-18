# Writing a Morphwheel plugin

A plugin adds targets to the wheel: a folder with a `plugin.toml` and one Python module (or
package) that converts a file. Morphwheel's own converters are written against the same API, so
whatever the built-in JPG target can do, your plugin can do too. This page is the whole contract.

## A converter in thirty lines

[`examples/sample_plugin/`](../examples/sample_plugin/) is a complete plugin that converts images
to BMP. Its converter, with only the module docstring left out:

```python
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
```

A converter is a class with one method. Morphwheel creates one instance per worker process and
calls `convert` once per file.

## The contract

**`ctx`** is a `ConversionContext` with:

| Member | What it is |
|---|---|
| `ctx.input_path` | The source file. Read it; never write to it, rename it or delete it. |
| `ctx.output_path` | A temporary file Morphwheel created, empty. Write your result there and nowhere else. Morphwheel renames it to its final name afterwards: the source's name with the output's extension (` (compressed)` for a compress target; ` (1)`, ` (2)` on a clash), beside the source, or in `Downloads\Morphwheel` when nothing can be created beside the source (a read-only folder, Controlled Folder Access). |
| `ctx.target_id` | The target's id as you declared it in `plugin.toml` (`"bmp"` in the sample), for a converter with several targets. |
| `ctx.options` | The user's presets, the same mapping for every plugin: `jpeg_quality`, `webp_quality`, `avif_quality`, `compress_longest_side`, `compress_quality`. Read-only; read them or ignore them. |
| `ctx.progress(fraction)` | Optional. `0.0` to `1.0`; call it for long conversions. It never raises and it is cheap: only steps of 0.05 are passed on, so not every call shows. |

**Errors.** Raise one of these from `morphwheel.plugins.api` for an expected failure. The toast
shows a fixed sentence per error; your message goes to the log, so make it say what a reader of
the log needs, without file paths:

| Raise | When | The toast says |
|---|---|---|
| `UnreadableInputError` | The input can't be decoded: damaged, truncated, not what its extension says | The file couldn't be read. |
| `UnsupportedAnimatedError` | The input is an animated image (out of scope in v0.1) | Animated images aren't supported. |
| `EngineMissingError` | Meant for the HEIC engine: the toast names HEIC, so for anything else raise `ConversionError` | HEIC support isn't installed. |
| `ConversionError` | Anything else you expected | The converter reported an error. |

Any other exception is a plugin error too ("The converter reported an error."), with the
traceback in the log; an `OSError` while writing is reported as a write failure or a full disk,
and running out of memory as a plugin error. An empty output file counts as a plugin error.
Raising never harms the source: Morphwheel discards the temporary file.

**What a plugin may import:** the standard library, what Morphwheel bundles (Pillow 13, and
`platformdirs`), and pure Python inside its own folder. There is no `pip`: the worker's import
path is the app's own environment plus your folder, appended last.

**Where it runs.** In a worker process without Qt, never in the app itself. Morphwheel reads
`plugin.toml` only; your module is imported the first time a file is dropped on one of your
targets. A crash takes down that worker and the file fails as "worker crashed"; the app and the
other workers carry on. A conversion has 120 seconds; after that the worker is replaced and the
file fails as "The conversion took too long and was stopped." Before and after every conversion,
Morphwheel fingerprints the source (size, modification time, file id, and a hash for sources up
to 64 MB); if anything changed, the output is discarded and the user gets a persistent alert.
That is the guard against a converter that touches its input, yours included.

## The manifest

```toml
[plugin]
id = "sample_plugin"                  # starts with a letter or digit; lowercase letters, digits, '.', '_', '-'; at most 64
name = "Sample plugin"                # shown on the Plugins page; at most 80 characters
version = "0.1.0"                     # at most 40 characters, shown beside the name
api = "0.1"                           # the API version this converter was written against
entry = "sample_plugin:Converter"     # module:Class, or package.module:Class

[[targets]]
id = "bmp"                            # lowercase letters, digits, '_', '-'; at most 32; unique in this file
label = "BMP"                         # the text on the wheel; at most 16 characters
output = "bmp"                        # the output format (see below)
accepts = ["png", "jpeg", "webp", "gif", "tiff"]   # the input formats it takes
```

- **Formats** are `jpeg`, `png`, `webp`, `avif`, `heic`, `bmp`, `tiff`, `gif`, `ico`, `pdf`. A
  `convert` target names its `output`, and `accepts` must not include it. Morphwheel decides which
  files a target can take from `accepts`, and shows the target disabled for the rest.
- **`kind = "compress"`** makes a target that keeps the input format and has no `output`;
  Morphwheel discards the result if it isn't smaller than the source.
- **`api`** is `MAJOR.MINOR`. While the major is 0, both must match the app's (`0.1` today); from
  1.0 on, only the major must match. A mismatch shows the plugin as broken, with the reason.
- **`slot`** is honored only for Morphwheel's bundled plugin. Third-party targets live in the More
  arc, in the order the user sets on the Plugins page; the arc shows the first six targets.
- **Target ids are namespaced** for you: your `bmp` is `sample_plugin:bmp` to the app, so two
  plugins can both offer a `tiff`.

## One module or one package, in its own folder

Morphwheel imports your entry by its module name, in a worker whose import path starts with the
app's own code. So that a plugin can never run another plugin's code, or the app's, under its
own name, the loader refuses a load unless every module it brought in from a plugin folder sits
under *your* folder and under your entry's top-level name:

- **Name the module after the plugin id** (`sample_plugin.py` for `sample_plugin`; an id's dots and
  hyphens become underscores, since a module name is an identifier). That is advice: any name is
  allowed except `morphwheel`, `PIL`, `pillow_heif` and Python's standard-library names, which the
  manifest refuses up front.
- **Helpers go inside a package**, imported relatively: `sample_plugin/__init__.py` and
  `sample_plugin/helpers.py` with `from .helpers import …`. A sibling `helpers.py` beside the entry
  module is refused, because another plugin could pick it up first.
- **Two plugins sharing a module name** can't both be used: enabled plugins keep their name, in the
  page's order, and the other one shows as broken with the owner named. Installing a plugin never
  breaks one that already works.

## Installing a plugin

1. Copy the folder to `%APPDATA%\Morphwheel\plugins\<id>\`, where `<id>` is the `id` from
   `plugin.toml` (`plugins\sample_plugin\`). The folder must be a real folder, not a link.
2. Open the tray's **Settings…**, choose **Plugins**, and click **Rescan**. The plugin appears
   unchecked. (**Open plugins folder** takes you to the right place; it creates the folder if need
   be.)
3. Tick the row and confirm the prompt. Plugins run Python code with your permissions, which is
   why nothing runs before you say so. Untick to disable; no prompt.
4. Shift-drag a file: your targets are in the More arc (the NW slot). Drag rows on the page, or
   use **Move up** and **Move down**, to order the arc.

A plugin you edit in place needs another **Rescan**: the workers are replaced so the new code
loads (a tick or untick alone gives the workers the new list before their next file; one in
flight finishes first). The trust record is `[plugins] enabled` in
`%APPDATA%\Morphwheel\settings.toml`, keyed by id, and `order` is the arc order.

## Troubleshooting

The Plugins page lists folders it can't use, with a reason:

| The page says | What to do |
|---|---|
| No plugin.toml | Put `plugin.toml` directly in the plugin's folder (a zip often adds a level). |
| plugin.toml must be inside a plugin folder | A `plugin.toml` sits at the root of the plugins folder; move it into `<id>\`. |
| The folder name doesn't match the plugin id | Rename the folder to the `id` (case doesn't matter). |
| The manifest is invalid | The reason names the field: fix it and Rescan. |
| Another plugin has this id | Two folders claim one `id`; rename one of them in its manifest and its folder. |
| The plugin's module name is used by another plugin | Rename the module and the `entry`; the id is a safe name. |
| Links aren't followed; copy the folder here | Copy the folder (or the manifest) instead of linking it. |
| Can't read this plugin | Something unexpected in the manifest; the log has the traceback. |

A manifest that isn't UTF-8 text, or is larger than 64 KiB, shows as invalid. Folders whose name
starts with `.` or `_` are skipped without a word.

A plugin that loads but fails on every file says so in the toast; the detail is in
`%LOCALAPPDATA%\Morphwheel\logs\morphwheel.log` (**Open log folder** in the tray menu). "resolves
outside the plugin's folder", "is a module of its own beside …" and "is a folder without
`__init__.py`" are the loader's rules from the previous section.

## Checklist before you publish

- The folder holds `plugin.toml` and your module or package, nothing the user has to install.
- The module is named after the id; helpers are inside the package.
- Expected failures raise the API's errors, with messages written for the log.
- The converter writes only `ctx.output_path` and never opens the input for writing.
- It works from a worker: copy the folder into the plugins folder, Rescan, enable, convert.
