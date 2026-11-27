# The showcase website

`site/` holds the project's one-page website, served at **https://morphwheel.yuvalrahamim.com** by
Cloudflare Pages (free plan). It is plain HTML and CSS: no build step, no dependencies, no scripts,
no cookies and no analytics.

| File | What it is |
|---|---|
| `site/index.html` | The page: the headline, the demo (with a pause toggle), the features, the formats, install, the FAQ, and the footer with the maker's credit (Yuval Rahamim, linked to yuvalrahamim.com and LinkedIn). The `<head>` holds the search and share metadata (`author` included) and two JSON-LD blocks (`SoftwareApplication`, with its `author`, and `FAQPage`) |
| `site/styles.css` | All styles and the demo's timeline. Dark by default, light when the OS prefers it |
| `site/404.html` | The page Pages serves for an unknown path |
| `site/robots.txt`, `site/sitemap.xml` | Allow every crawler; the one-page sitemap |
| `site/_headers` | Response headers for Pages: a strict Content-Security-Policy (no inline styles or scripts), `nosniff`, HSTS (a year, subdomains included), the referrer and permissions policies, a week's cache on `assets/` |
| `site/assets/wheel-idle-*.webp`, `wheel-jpg-*.webp` | The wheel at size M, light and dark: as it opens over `lake.png`, and with JPG hovered. Drawn by the app's renderer |
| `site/assets/toast-*.webp` | The success toast (`Converted to JPG`), light and dark: the app's own `ToastWidget`, rendered |
| `site/assets/thumb-*.webp` | The demo's four Explorer thumbnails (drawn scenes, 192 by 144) |
| `site/assets/og.png` | The share image (1200 by 630): the dark JPG-hovered wheel frame and the headline |
| `site/assets/icon.svg`, `icon-256.png` | Copies of `assets/icon/morphwheel.svg` and `morphwheel-256.png` |

## The demo

The demo is one 10-second CSS loop, with no script: File Explorer is sketched in HTML, while the
wheel and the toast are images of the real thing. It plays the real sequence: press on `lake.png`,
drag, Shift (the wheel opens at the cursor and stays open after Shift is released), aim at JPG, drop,
and `lake.jpg` appears beside the original as the toast rises. Every animated part shares the same
duration and percentages in `styles.css`, and the captions under the stage run on the same clock.
The stage is a 1000 by 600 design-pixel space (`--u`, through a container query), so it scales as
one picture. With reduced motion the loop stops on the moment before the drop.

The page links to `releases/latest` and never names a version, so a release needs no site change.
Keep its claims in step with `README.md`: the promises, the formats, the install notes.

## Motion and layout

Everything moves with CSS alone: the CSP allows no script.

- **Smooth scrolling** for the page's own links (`scroll-behavior`), landing below the header
  (`scroll-padding-top`).
- **A sticky header**, translucent with a blur. Its bottom line fades in once the page scrolls (a
  scroll-driven animation; where those aren't supported the line is always there). On phones
  (560 px and narrower) the GitHub link is hidden: the hero and the footer link the repository too.
- **The hero rises in on load**, line by line, then the demo.
- **Sections rise in as they scroll into view** (`animation-timeline: view()`): the features (a
  slight stagger across each row), the formats, install, the FAQ and the footer. Where
  scroll-driven animations aren't supported, everything is simply visible.
- **The FAQ slides open and closed** (`::details-content` with `interpolate-size`), and its `+`
  turns into a `×`. Browsers without `interpolate-size` open the answer at once.
- **Buttons lift on hover and press on click.** Touch screens get taller text links
  (`pointer: coarse`).
- **Reduced motion** (Windows' "Animation effects" off) turns all of it off, the demo included.
  Printing turns every animation off too.

Each feature has a small stroked icon (inline SVG, no image request), in the accent color.

## Search and answer engines

- **Title and description** carry what people search for ("image converter", "Windows", "File
  Explorer", the formats), and stay under about 60 and 155 characters.
- **The FAQ is written twice:** once as the visible `<details>` list and once as the `FAQPage`
  JSON-LD in `<head>`. Change both together, word for word; search engines expect them to match.
- **The `SoftwareApplication` block** states the facts an answer engine looks for: free, MIT, the
  Windows versions, the download, the repository, the features. It names no version.
- **Not on the page, on purpose:** the winget command (add it to the install section once the
  package is accepted into winget-pkgs), the plugin API beyond one FAQ answer, build and developer
  details (the repository has them), and version numbers.
- The JSON-LD blocks are data, not scripts: the CSP's `default-src 'none'` doesn't affect them.

## Previewing it locally

```powershell
.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory site
```

Then open http://127.0.0.1:8765. The local server ignores `_headers`; Pages applies it.
A browser may keep an old `styles.css`: reload without the cache after a change.

## Deploying (one-time setup on Cloudflare)

1. In the Cloudflare dashboard, open **Workers & Pages**, choose **Create**, then the **Pages** tab,
   then **Import an existing Git repository**. Connect GitHub and grant the Cloudflare Pages app
   access to the `MorphWheel/morphwheel` repository only.
2. Project name `morphwheel` (it gives `morphwheel.pages.dev`). Production branch `main`.
3. Build settings: framework preset **None**, build command empty, build output directory **`site`**.
4. Save and deploy. Check `https://morphwheel.pages.dev`.
5. In the project's **Settings › Build › Build watch paths**, include only `site/*`, so commits that
   change only the app don't trigger a site build. Under **Preview deployments**, choose *None* or
   limit them to branches you want previewed.

From then on every push to `main` that touches `site/` deploys the site.

## The custom domain (DNS at GoDaddy)

Add the domain in Cloudflare **first**, then the DNS record; a CNAME that points at Pages before the
domain is added returns errors.

1. In the Pages project, open **Custom domains › Set up a custom domain**, and enter
   `morphwheel.yuvalrahamim.com`. Cloudflare shows the CNAME it expects and waits.
2. In GoDaddy, open the domain `yuvalrahamim.com` › **DNS** › **Add new record**:

   | Type | Name | Value | TTL |
   |---|---|---|---|
   | CNAME | `morphwheel` | `morphwheel.pages.dev` | 1 hour |

3. Back in Cloudflare the domain turns **Active** once the record resolves (minutes, sometimes
   longer), and Cloudflare issues the HTTPS certificate itself.

Nothing else on `yuvalrahamim.com` changes: the zone stays at GoDaddy, and only this one name points
at Cloudflare.

## Regenerating the images

The wheel and toast images come from the app's code, so they stay true when the wheel or the toast
changes. Render with Qt's Windows platform (`QT_QPA_PLATFORM=windows`: the offscreen platform has no
fonts and draws boxes) at a 2.0 pixel ratio, with `Theme.build(Scheme.LIGHT or DARK,
accent=QColor("#0078D4"))`:

- **The wheel:** the test helpers in `tests/unit/builtin_targets.py`,
  `planned_session(Catalog.of(BUILTINS), ("lake.png",), WheelGeometry.for_size("M"))`; the pointer
  near the hub with `HubText("lake.png", "1 file")` for the idle frame, and over JPG with
  `HubText("→ JPG", "1 file")` and `Frame(bulge={SlotPos.N: 1.0})` for the hovered one. Paint with
  `paint_content` alone (no catch floor) into `blank_layer`, uncropped, so the frames stack.
- **The toast:** `ToastWidget(ToastModel(ToastKind.SUCCESS, "Converted to JPG",
  "lake.jpg · 2.4 MB → 386 KB", ...), theme, Motion(False))` with the *Show in folder* and *Undo*
  actions, rendered into a transparent image.

The share image `og.png` is the dark JPG frame scaled to 720 px on a `#0c0c0d` canvas, with the icon,
the headline in Segoe UI Bold and two lines in Segoe UI.

Save the frames as WebP. Keep the file name short: at size M the hub elides a long name (`photo.png` becomes
`ph…ng`).
