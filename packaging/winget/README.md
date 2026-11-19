# winget manifests

The three files here are templates for the [winget-pkgs](https://github.com/microsoft/winget-pkgs)
manifests of **`MorphWheel.Morphwheel`** (moniker `morphwheel`), in the multi-file form at manifest
schema 1.28.0. The release workflow renders them for every build; the pull request to winget-pkgs is
a human step.

## What the release workflow does

After the installer is built (and signed, on a tag push), `tools/release.py winget` fills the
placeholders and writes the result under `packaging/output/installer/winget/`, in winget-pkgs'
layout, so it rides in the run's artifact next to the installer:

```
manifests/m/MorphWheel/Morphwheel/<version>/
  MorphWheel.Morphwheel.yaml
  MorphWheel.Morphwheel.installer.yaml
  MorphWheel.Morphwheel.locale.en-US.yaml
```

| Placeholder | Value |
|---|---|
| `@version` | the release version (`v<version>` is the tag) |
| `@sha256` | SHA-256 of the installer file given, upper-case hex: the signed installer on a tag push |
| `@url` | `https://github.com/MorphWheel/morphwheel/releases/download/v<version>/morphwheel-<version>-setup.exe` |
| `@date` | `ReleaseDate`, the build date (UTC) unless `--date` is given |
| `@notes_url` | the GitHub Release page |

The tool refuses an installer that is not named `morphwheel-<version>-setup.exe`, a date that is not
`YYYY-MM-DD`, and a template set that uses anything but exactly these five placeholders (a lost
placeholder would otherwise render a half-filled manifest). `$` is plain text, so the
`yaml-language-server: $schema=` comments survive; a literal `@` would be written `@@`.

By hand, for a published release:

```powershell
python tools/release.py winget 0.1.0 --installer path\to\morphwheel-0.1.0-setup.exe -o out
winget validate --manifest out\manifests\m\MorphWheel\Morphwheel\0.1.0
```

`winget validate` is the proof that the rendered set is a valid manifest. `tests/unit/test_winget.py`
runs it wherever winget is on `PATH` (locally and on the GitHub-hosted runner) and skips otherwise.
A client older than the manifest schema validates under the newest schema it knows and warns that
the `$schema` header names a newer one; the test tolerates that one warning and no other. The
structural checks in that test run everywhere.

## The choices in the installer manifest (RD-32)

- **One installer: x64, `inno`, `Scope: user`.** The installer is per-user
  (`PrivilegesRequired=lowest`, into `%LOCALAPPDATA%\Programs\Morphwheel`), Windows 10 22H2 or
  later (`MinimumOSVersion: 10.0.19045.0`, the script's `MinVersion`).
- **`ElevationRequirement: elevationProhibited`.** winget then refuses to install from an elevated
  terminal instead of running the installer, which would refuse on its own (RD-30e). Same rule,
  two layers.
- **No `InstallerSwitches`.** winget's built-in Inno switches (`/SP- /VERYSILENT /SUPPRESSMSGBOXES
  /NORESTART`; `/SILENT` for `silentWithProgress`) are right for this installer. winget passes no
  scope switch for Inno. A silent run leaves the "start with Windows" choice alone (RD-30c), and
  `/SUPPRESSMSGBOXES` means the installer's own refusals take their default answer instead of
  waiting for a click under `winget upgrade`.
- **`ProductCode` is `{5D597E37-BBB5-46D5-853A-E4A925193830}_is1`**: Inno's uninstall key name,
  the script's `AppId` plus `_is1`. It is how winget correlates the installed copy for `upgrade` and
  `uninstall`; the `AppsAndFeaturesEntries` row mirrors what Inno writes (`DisplayName`,
  `Publisher`). `UpgradeBehavior: install` runs the new setup over the old one (the script cleans
  `_internal` first, RD-30f).
- **Stable versions only.** winget-pkgs takes release versions under `MorphWheel.Morphwheel`; the
  tool renders a prerelease (the rehearsal does) but prints a warning. A preview channel would be a
  separate `MorphWheel.Morphwheel.Preview` package. The identifier is permanent once merged.

## Opening the pull request (human step)

1. Publish the draft GitHub Release first: the `InstallerUrl` must be downloadable and the SHA-256
   must match the published asset.
2. Take `manifests/` from the run's artifact (or render it by hand as above) and copy the version
   folder into a fork of winget-pkgs at the same path, or feed the folder to
   [wingetcreate](https://github.com/microsoft/winget-create) or
   [komac](https://github.com/russellbanks/Komac).
3. Open the PR. The pipeline there installs the package on a clean VM; `tests/unit/test_winget.py`
   and `winget validate` locally are what we can check beforehand.
