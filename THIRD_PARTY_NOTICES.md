# Third-party notices

Morphwheel is released under the [MIT License](LICENSE). The installer also ships the components
below, each under its own license. The full license texts are installed with the app, under
`%LOCALAPPDATA%\Programs\Morphwheel\_internal\licenses\` (one folder per component), and the
same texts are in this repository where a package does not carry them (`packaging/licenses/`).

This file names every component in the installer as built. The build collects the texts
automatically (`packaging/pyinstaller/bundle_licenses.py`) and a test holds this file to what the
build ships.

## Runtime

| Component | Version | License | Text in the installed app |
|---|---|---|---|
| Python | 3.12 | PSF License 2.0 | `licenses\Python-3.12\LICENSE.txt` |
| Qt (via PySide6-Essentials) | 6.12.0 | LGPL-3.0-only | `licenses\Qt\LGPL-3.0.txt` (and `GPL-3.0.txt`, which the LGPL refers to) |
| PySide6-Essentials, shiboken6 (the Python bindings for Qt) | 6.12.0 | LGPL-3.0-only | `licenses\Qt\LGPL-3.0.txt` |
| Pillow | 13.0.0 | MIT-CMU (HPND) | `licenses\pillow-13.0.0\LICENSE`, which also carries the texts of the libraries compiled into it (next section) |
| platformdirs | 4.13.4 | MIT | `licenses\platformdirs-4.13.4\LICENSE` |
| tomli-w | 1.2.0 | MIT | `licenses\tomli-w-1.2.0\LICENSE` |

### Inside Python's Windows build

Python's Windows distribution links these libraries; the installer ships them as Python ships
them (`libcrypto-3.dll`, `libssl-3.dll`, `libffi-8.dll` and the `_bz2`, `_lzma`, `pyexpat` and
`_decimal` extension modules; zlib is inside `python312.dll`). Python's `LICENSE.txt` carries the
bzip2 and libffi notices and the Apache License; OpenSSL, Expat, libffi, zlib and libmpdec are
documented in Python's
[Licenses and Acknowledgements for Incorporated Software](https://docs.python.org/3.12/license.html);
liblzma's license (0BSD) is the same text as the `===== xz-5.8.4 =====` section of
`licenses\pillow-13.0.0\LICENSE`, and at <https://github.com/tukaani-project/xz/blob/master/COPYING>.

| Component | Version | License |
|---|---|---|
| OpenSSL | 3.0.16 | Apache-2.0 |
| libffi | (as shipped with Python 3.12) | MIT |
| bzip2 | 1.0.8 | bzip2 license (BSD-style) |
| XZ Utils (liblzma) | (as shipped with Python 3.12) | 0BSD / public domain |
| Expat | 2.7.1 | MIT |
| libmpdec | 2.5.1 | BSD-2-Clause |
| zlib | 1.3.1 | zlib license |

Python's `LICENSE.txt` also carries the *Additional Conditions for this Windows binary build*
for the Microsoft Distributable Code embedded in Python's binaries; the Visual C++ runtime files
below are covered by the same terms.

### Inside Pillow

On Windows, Pillow compiles its image libraries into its own extension modules, so there are no
separate DLLs. Every library below is listed, with its text, in `licenses\pillow-13.0.0\LICENSE`
(the `===== name-version =====` sections), except aom, whose texts Pillow's file omits and which
are therefore shipped separately.

| Library | Version | License | Used for |
|---|---|---|---|
| brotli | 1.2.0 | MIT | WOFF2 fonts in FreeType |
| freetype | 2.14.3 | FreeType License (FTL) | text rendering |
| harfbuzz | 14.5.0 | MIT ("Old MIT") | text shaping in FreeType |
| lcms2 | 2.19.1 | MIT | color management |
| libavif | 1.4.2 | BSD-2-Clause (with the libyuv BSD-3-Clause and dav1d BSD-2-Clause notices it includes) | AVIF |
| aom | (as compiled into libavif 1.4.2) | BSD-2-Clause and the Alliance for Open Media Patent License 1.0 | the AVIF encoder; texts in `licenses\aom\LICENSE.txt` and `PATENTS.txt` |
| dav1d | (as compiled into libavif 1.4.2) | BSD-2-Clause (VideoLAN and dav1d authors) | the AVIF decoder |
| libjpeg-turbo | 3.2.0 | IJG, BSD-3-Clause and zlib (its three component licenses) | JPEG |
| libpng | 1.6.58 | PNG Reference Library License v2 | PNG |
| libwebp | 1.6.0 | BSD-3-Clause | WebP |
| openjpeg | 2.5.4 | BSD-2-Clause | JPEG 2000 |
| tiff | 4.7.2 | libtiff license (MIT-style) | TIFF |
| xz | 5.8.4 | 0BSD | LZMA-compressed TIFF |
| zlib-ng | 2.3.3 | zlib license | PNG and deflate |

Not in this build: libimagequant (GPL-3.0), raqm and FriBiDi (LGPL-2.1), and the rav1e and SVT-AV1
encoders. Pillow's generic SBOM lists them among the libraries its wheels *may* link; the Windows
wheel does not, and a test (`tests/unit/test_packaging.py`) fails if a Pillow upgrade changes that.

### Microsoft Visual C++ Runtime

`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `MSVCP140.dll`, `MSVCP140_1.dll` and `MSVCP140_2.dll`
are Microsoft Visual C++ Redistributable files, shipped under Microsoft's redistribution terms
for the Visual C++ runtime (see the *Additional Conditions* in Python's `LICENSE.txt`).

## Build and installer tools

| Tool | Version | License | Where it is |
|---|---|---|---|
| PyInstaller (bootloader) | 6.22.3 | GPL-2.0-or-later **with the PyInstaller bootloader exception**: the exception lets the bundled program be distributed under any license, and places no condition on Morphwheel | the start-up code of `morphwheel.exe` and `morphwheel-worker.exe` |
| Inno Setup | 6.7 | Inno Setup License (the setup stub may be redistributed freely) | the installer executable itself |

## Qt and the LGPL

Qt and its Python bindings are used under the GNU Lesser General Public License, version 3. The
obligations that matter to a user:

- **The texts are shipped** (`licenses\Qt\LGPL-3.0.txt`, with `GPL-3.0.txt`, which section 4 of
  the LGPL incorporates).
- **Qt is dynamically linked and replaceable.** The Qt libraries are separate files in the
  installed app, under `_internal\PySide6\` (`Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`,
  `Qt6Network.dll`, `Qt6Svg.dll`, the `plugins\` folder and the `translations\` folder), with the
  bindings beside them (`PySide6\*.pyd`, `pyside6.abi3.dll`, `shiboken6\`). You may replace them
  with your own build of the same Qt version, as the LGPL allows; Morphwheel loads whatever is in
  that folder.
- **Source code.** Qt's source is at <https://code.qt.io/> and
  <https://download.qt.io/official_releases/qt/>; PySide6's and shiboken6's at
  <https://code.qt.io/cgit/pyside/pyside-setup.git/> and
  <https://download.qt.io/official_releases/QtForPython/>. Morphwheel ships the Qt libraries and
  bindings from the PyPI wheels unmodified, omitting the Qt modules and plugins the app does not
  use (the build's exclusion list is in `packaging/pyinstaller/morphwheel.spec`).
- **Qt's own third-party components** (for example PCRE2, HarfBuzz and FreeType inside Qt) are
  listed, with their licenses, at <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

Morphwheel makes no modification to Qt or to the bindings; it only leaves out files.

## Not shipped: the opt-in HEIC engine

HEIC and HEIF input is an opt-in download (decision A6), never part of the installer: the
`pillow-heif` wheel is itself BSD-3-Clause, but it bundles libheif (LGPL-3.0), libde265 (LGPL-3.0)
and x265 (GPL-2.0), among others (see its `LICENSES_bundled.txt`). When you choose **Install HEIC
support** in the app, Morphwheel downloads pillow-heif 1.8.1 from PyPI, verifies its SHA-256 and
keeps it in your profile (`%LOCALAPPDATA%\Morphwheel\engines\`), for your use only. Morphwheel
itself stays MIT. The download's own license texts are inside that wheel.

## Morphwheel's own assets

The app icon, the wheel, the UI and the translations are Morphwheel's own work, under the MIT
License. No third-party fonts or icon sets are bundled; text is rendered with the fonts Windows
provides.
