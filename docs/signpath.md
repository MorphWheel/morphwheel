# Code signing through SignPath Foundation

Morphwheel's release workflow signs the two executables and the installer through SignPath when the
repository carries the SignPath variables (see [`architecture.md`](architecture.md), packaging, and
RD-31 in [`decisions.md`](decisions.md)). The certificate is issued to SignPath Foundation, which
grants free signing to open-source projects that meet its
[conditions](https://signpath.org/terms). This page holds the readiness check against those
conditions, the drafted answers for the [application form](https://signpath.org/apply), and the
setup that follows an approval. The facts about the program were read from signpath.org on
2026-11-23; the Foundation notes that its code of conduct is still a draft, so re-read the terms
before applying.

## The conditions, checked against the project

| Condition (signpath.org/terms) | Morphwheel | Status |
|---|---|---|
| No malware or potentially unwanted programs | A file converter; the Defender scans of every measured build are clean (S0, S7 reports) | ✅ |
| An OSI-approved license without commercial dual-licensing, for all components | MIT for the project; the bundle is Python (PSF), Qt and PySide6 (LGPL-3.0), Pillow (MIT-CMU) and the rest listed in `THIRD_PARTY_NOTICES.md`. pillow-heif (GPL) is never bundled (A6) | ✅ |
| No proprietary component | None | ✅ |
| Actively maintained | Yes | ✅ |
| **Released in the form that should be signed** | **No release exists yet.** The Foundation signs a project that already ships, so the first installer must be published (unsigned) before the application can be accepted | ❌ gate |
| Functionality documented on the download page | The README describes the app; the release notes come from `CHANGELOG.md` | ✅ |
| Sign your own project and your own binaries only | One team writes the code, the build scripts and the workflow | ✅ |
| No hacking tools | None | ✅ |
| Respect user privacy: data sent elsewhere needs a privacy policy, a notice and an opt-out | The app makes no network request except the opt-in HEIC engine download, asked for by the user through a consent dialog; `PRIVACY.md` documents it. The Foundation's standard sentence ("will not transfer any information ... unless specifically requested by the user") is true of the app | ✅ |
| Announce system changes | The only system change is the per-user Run value for autostart, behind an opt-in checkbox (default off) in the installer and in Settings | ✅ |
| Provide uninstallation | Inno Setup's uninstaller; it asks before removing the data folders | ✅ |
| Multi-factor authentication for every team member, on SignPath and on GitHub | 👤 The GitHub account must have 2FA on. The organization does not yet *require* 2FA for its members (recommended in the tracker since S0) | 👤 |
| Code signing roles: Authors, Reviewers, Approvers | A single maintainer holds all three roles; every signing request is approved by hand in SignPath | ✅ (one person) |
| A "Code signing policy" on the home page and the download or release pages, with the attribution sentence, the team roles and the privacy policy | Not yet. The README has an *unsigned for now* note; the section below replaces it once signing is approved, and the release notes get a one-line pointer | ⏳ after approval |
| Signed binaries carry product name and version metadata, enforced by metadata restrictions in the artifact configuration | Both executables share `file_version_info.txt`: `ProductName` Morphwheel, one `ProductVersion` per build, held to `__version__` by a test. The installer's version resource is set from the executable's | ✅ |
| Binaries are built from source in a verifiable way, by an automated build (origin verification) | GitHub Actions builds everything from the tagged commit; the signing step hands over the run's own artifact | ✅ |
| Every release needs manual approval for signing | The workflow waits for the approval up to one hour (`wait-for-completion-timeout-in-seconds: 3600`). The approver must act within that hour, or the run fails and the tag has to be re-run | ⚠️ note |

Acceptance is at the Foundation's discretion, and the form asks for evidence of reputation (users,
coverage, download numbers). A brand-new project has little to show there; the honest answer below
names what exists.

## The order this implies

1. Publish v0.1 **unsigned**: the README already says so, and the checksum file covers verification.
2. Apply, pointing at that release.
3. On approval, configure SignPath and the repository (below), add the code signing policy section,
   and ship the next release signed.

## Draft answers for the application form

The form (read on 2026-11-23) has these fields; a star marks a required one. The personal fields are
left to the applicant.

| Field | Answer |
|---|---|
| Project Name* | Morphwheel |
| Repository URL* | https://github.com/MorphWheel/morphwheel |
| Homepage URL* | https://github.com/MorphWheel/morphwheel (no separate website) |
| Download URL | https://github.com/MorphWheel/morphwheel/releases. The form says this page must mention that the project uses SignPath Foundation for code signing: the release notes and the README carry the code signing policy line (below) |
| Privacy Policy URL | https://github.com/MorphWheel/morphwheel/blob/main/PRIVACY.md |
| Wikipedia URL | none |
| Tagline* | Shift-drag a file in Windows File Explorer, drop it on a radial wheel, and get it converted. |
| Category* | a drop-down; choose the closest to *Utilities* or *Desktop tools* |
| Description* | Morphwheel is an open-source (MIT) file converter for Windows. While dragging a file in File Explorer, the user presses Shift and a radial wheel appears at the cursor; dropping the file on a slice converts it (images to JPG, PNG, WebP and more, compression, resizing) into a new file beside the source. The source file is never modified, moved or overwritten. There is no telemetry and no account; the one optional network request downloads the HEIC decoder on the user's explicit request. Conversions run in separate worker processes, and third parties can add formats through a small plugin API. The app is built with Python and Qt (PySide6) and ships as a per-user installer. |
| Reputation* | A new project: the first public release is v0.1.0 (link the release). What exists: the public repository with CI on every push, about 1 100 automated tests including a 126-case matrix for the drop-safety rule, an architecture document, a privacy policy and a security policy with private vulnerability reporting, and a winget manifest prepared for the community repository. Add any coverage or user numbers that exist by the time of applying |
| Maintainer Type | Individual |
| Build System* | GitHub Actions |
| First Name*, Last Name*, Email* | the applicant's own; the SignPath account is created from them |
| Company Name | leave empty |
| Primary Discovery Channel* and exact source | the applicant's own answer |
| Code of Conduct checkbox* | read https://signpath.org/terms first; the certificate is issued in the Foundation's name and can be revoked |
| Personal data checkbox* | required to submit |
| Other communications checkbox | optional; not needed |

## The README section, once signing is approved

Add under *Install*, replacing the *Code signing* bullet, and keep the heading text exactly
"Code signing policy" (the Foundation looks for that term):

```markdown
## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

- **Team:** the [MorphWheel organization members](https://github.com/orgs/MorphWheel/people) are
  the committers and reviewers; the organization owners approve each signing request.
- **Privacy:** this program will not transfer any information to other networked systems unless
  specifically requested by the user or the person installing or operating it. See
  [PRIVACY.md](PRIVACY.md).
- Releases from v0.x.y on are signed; `SHA256SUMS.txt` beside each installer lets you verify a
  download either way. The installer's uninstaller stub stays unsigned (a limitation of the
  signing step).
```

The release notes (`CHANGELOG.md`, rendered by `tools/release.py notes`) get one line pointing at
that section. The signing paragraph in `SECURITY.md` changes from *applied for* to the same pointer.

## After approval: the setup (tracker item 15)

In SignPath:

1. A project for the repository, with GitHub Actions as the trusted build system, so origin
   verification ties each signed file to the run that built it.
2. Two artifact configurations: a zip of `morphwheel.exe` and `morphwheel-worker.exe`, and a zip of
   `morphwheel-<version>-setup.exe`, each with metadata restrictions (product name Morphwheel, the
   version equal across the files of one build).
3. A signing policy for releases that requires manual approval, and an API token for the workflow.

In the repository (RD-31):

- The variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY_SLUG`,
  `SIGNPATH_CONFIG_EXES`, `SIGNPATH_CONFIG_INSTALLER`, and the secret `SIGNPATH_API_TOKEN`.
- A tag ruleset on `v*`, so only administrators can create release tags.
- 2FA required for the organization's members.

Then a tag push signs. The approval must be given within the hour the workflow waits.
