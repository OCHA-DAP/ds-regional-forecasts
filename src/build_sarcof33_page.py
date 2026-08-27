"""Build the (to-be-encrypted) SARCOF-33 review page.

Self-contained HTML: the digitized 2026/27 consensus maps rendered per
season, side-by-side with the earliest archived MME map for each previous
target year of the same season, plus per-country time-series facets (raw
SEAS5 percentile line, MME wet-lean dots, SARCOF-33 consensus diamond).
Everything is inlined (base64 / SVG) so the single output file can be
staticrypt-ed; the plaintext lives under data/ (gitignored) and must NEVER
be committed or uploaded — only the encrypted docs/sarcof33.html is.

Usage:  uv run python -m src.build_sarcof33_page
then:   npx staticrypt data/tmp/sarcof33_page/sarcof33.html \
          -p anticipation2026 --remember 7 -d docs
"""

import base64
import io
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
OUT_DIR = ROOT / "data" / "tmp" / "sarcof33_page"
RAW_IMG = ROOT / "data" / "raw" / "sadc" / "osf-seasonal"

SEASONS = ["OND", "NDJ", "DJF", "JFM"]
SEASON_START = {"OND": 10, "NDJ": 11, "DJF": 12, "JFM": 1}
SEASON_LABEL = {"OND": "OND 2026", "NDJ": "NDJ 2026/27", "DJF": "DJF 2026/27", "JFM": "JFM 2027"}
S5_MONTH = {"OND": "08", "NDJ": "08", "DJF": "08", "JFM": "09"}

PAL = {1: (198, 156, 109), 2: (238, 221, 57), 3: (64, 189, 176), 4: (28, 32, 199)}
CLASS_LABEL = {1: "Below-Normal", 2: "Normal-to-Below", 3: "Normal-to-Above", 4: "Above-Normal"}
ISO_NAMES = {"AGO": "Angola", "BWA": "Botswana", "COD": "DR Congo", "LSO": "Lesotho",
             "MDG": "Madagascar", "MOZ": "Mozambique", "MWI": "Malawi", "NAM": "Namibia",
             "SWZ": "Eswatini", "TZA": "Tanzania", "ZAF": "South Africa", "ZMB": "Zambia",
             "ZWE": "Zimbabwe"}
OSF_C, S5_C, NEW_C = "#12917f", "#eb6834", "#b3266d"


def b64(img: Image.Image, fmt="PNG", **kw) -> str:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def boundary_px(scale: int, lon0=10.0, lat0=8.0):
    gj = json.loads((ROOT / "data" / "tmp" / "sadc_continental.geojson").read_text())
    pts = []
    for f in gj["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                ring = np.array(ring)
                for i in range(len(ring) - 1):
                    a, b = ring[i], ring[i + 1]
                    n = max(1, int(np.hypot(*(b - a)) / 0.03))
                    for t in np.linspace(0, 1, n, endpoint=False):
                        p = a + t * (b - a)
                        pts.append(((p[0] - lon0) / 0.25 * scale, (lat0 - p[1]) / 0.25 * scale))
    return np.array(pts)


def render_sarcof(sel: xr.Dataset, scale=5) -> Image.Image:
    cls = sel["clazz"].values
    conf = sel["confidence"].values
    h, w = cls.shape
    img = np.full((h * scale, w * scale, 3), 255, np.uint8)
    for code, col in PAL.items():
        m = np.kron(cls == code, np.ones((scale, scale), bool))
        img[m] = col
    dark = np.kron(conf, np.ones((scale, scale), bool))
    # confidence: sparse dot texture
    yy, xx = np.mgrid[0:h * scale, 0:w * scale]
    dots = ((yy % 6 == 0) & (xx % 6 == 0))
    img[dark & dots] = (60, 60, 60)
    for x, y in boundary_px(scale):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < h * scale and 0 <= xi < w * scale:
            img[yi, xi] = (90, 90, 90)
    out = Image.fromarray(img)
    out.thumbnail((560, 1000), Image.LANCZOS)
    return out


def prior_images(season: str) -> list[tuple[str, str]]:
    """(caption, b64 jpg) for the earliest archived MME issue of each previous
    target year of this season."""
    start = SEASON_START[season]
    by_year = {}
    for f in sorted(RAW_IMG.glob(f"*/PRCP_prob-tercile-m_MME01_*_{season}.jpg")):
        m = re.search(r"MME01_(\d{4})-([A-Za-z]{3})_", f.name)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        iy, im_ = int(m.group(1)), months.index(m.group(2)) + 1
        ty = iy + (1 if start < im_ else 0)
        lead = (start - im_) % 12
        cur = by_year.get(ty)
        if cur is None or lead > cur[0]:
            by_year[ty] = (lead, f, f"{m.group(2)} {iy}")
    out = []
    for ty in sorted(by_year):
        lead, f, issued = by_year[ty]
        yl = f"{ty}" if season == "OND" else (f"{ty}/{str(ty + 1)[2:]}" if start >= 11 else f"{ty}")
        img = Image.open(f)
        img.thumbnail((560, 620), Image.LANCZOS)
        out.append((f"MME {season} {yl} · issued {issued}", b64(img.convert('RGB'), 'JPEG', quality=72)))
    return out


def facet_svg(iso: str, season: str, s5: dict, mme: list, newv: float | None,
              prior: list | None = None) -> str:
    Y0, Y1, W, H, mL, mR, mT, mB = 1993, 2027.6, 300, 130, 26, 6, 6, 16
    xs = lambda yr: mL + (yr - Y0) / (Y1 - Y0) * (W - mL - mR)
    ys = lambda v: mT + (100 - v) / 100 * (H - mT - mB)
    s = f'<rect x="{mL}" y="{ys(66.7):.1f}" width="{W - mL - mR}" height="{ys(33.3) - ys(66.7):.1f}" fill="#ececе7" opacity="0.9"/>'
    s = s.replace("ececе7", "ecece7")
    s += f'<line x1="{mL}" y1="{ys(50):.1f}" x2="{W - mR}" y2="{ys(50):.1f}" stroke="#dddcd5"/>'
    for lab, v in (("67", 66.7), ("33", 33.3)):
        s += f'<text x="{mL - 3}" y="{ys(v) + 3:.1f}" text-anchor="end">{lab}</text>'
    s += f'<text x="{mL - 3}" y="{ys(97):.1f}" text-anchor="end">wet</text><text x="{mL - 3}" y="{ys(3):.1f}" text-anchor="end">dry</text>'
    for yr in (1995, 2005, 2015, 2025):
        s += f'<text x="{xs(yr):.0f}" y="{H - 3}" text-anchor="middle">{yr}</text>'
    pts = sorted((int(y), v) for y, v in s5.items())
    if pts:
        s += f'<polyline fill="none" stroke="{S5_C}" stroke-width="1.3" opacity="0.85" points="' + \
             " ".join(f"{xs(y):.1f},{ys(v):.1f}" for y, v in pts) + '"/>'
        s += "".join(f'<circle cx="{xs(y):.1f}" cy="{ys(v):.1f}" r="{3 if y == 2026 else 1.8}" fill="{S5_C}"><title>SEAS5 {y}: p{v}</title></circle>' for y, v in pts)
    for y, v, mm in mme:
        s += f'<circle cx="{xs(int(y)):.1f}" cy="{ys(v):.1f}" r="3" fill="{OSF_C}" stroke="#fff" stroke-width="1"><title>MME issued {y}-{mm}: wet-lean {v}</title></circle>'
    for y, v, vintage in (prior or []):
        x, yy_ = xs(y + 0.35), ys(v)
        s += (f'<path d="M {x:.1f} {yy_ - 5:.1f} L {x + 4.3:.1f} {yy_:.1f} L {x:.1f} {yy_ + 5:.1f} L {x - 4.3:.1f} {yy_:.1f} Z" '
              f'fill="none" stroke="{NEW_C}" stroke-width="1.4"><title>SARCOF consensus {vintage}: wet-lean {v:.0f}</title></path>')
    if newv is not None:
        x, y = xs(2026.35), ys(newv)
        s += f'<path d="M {x} {y - 6} L {x + 5.2} {y} L {x} {y + 6} L {x - 5.2} {y} Z" fill="{NEW_C}" stroke="#fff" stroke-width="1"><title>SARCOF-33 consensus: wet-lean {newv:.0f}</title></path>'
    return (f'<div class="facet"><h4>{ISO_NAMES[iso]}</h4>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{ISO_NAMES[iso]} {season}">{s}</svg></div>')


def main() -> None:
    cons = xr.open_dataset(ROOT / "data" / "processed" / "sarcof-consensus" / "sarcof_consensus.nc")
    cstats = pd.read_parquet(ROOT / "data" / "processed" / "sarcof-consensus" / "sarcof_consensus_country_stats.parquet")
    cstats["wetlean"] = 50 - cstats.dryness_score * 50 / 70
    ts = json.loads((ROOT / "docs" / "data" / "timeseries.json").read_text())

    sections = []
    for season in SEASONS:
        figs = []
        official = Image.open(ROOT / "data" / "processed" / "sarcof33" / "maps" / f"{season}.png").convert("RGB")
        official.thumbnail((980, 980), Image.LANCZOS)
        figs.append(
            f'<figure class="hl wide"><img src="{b64(official, "JPEG", quality=82)}" '
            f'alt="Official SARCOF-33 {SEASON_LABEL[season]} map">'
            f'<figcaption><strong>Official SARCOF-33 map · {SEASON_LABEL[season]}</strong> · '
            f'CSC presentation, 26 Aug 2026</figcaption></figure>')
        for vintage in [str(v) for v in cons.vintage.values][::-1]:  # newest first
            sel = cons.sel(vintage=vintage, season=season)
            if int((sel["clazz"].values >= 0).sum()) == 0:
                continue  # season not drawn that year
            is_new = vintage == "2026/27"
            src_note = "digitized from the official presentation deck" if is_new else "digitized from the statement PDF"
            title = f"SARCOF-33 consensus · {SEASON_LABEL[season]}" if is_new else f"Consensus {season} {vintage}"
            figs.append(
                f'<figure{" class=hl" if is_new else ""}><img src="{b64(render_sarcof(sel))}" alt="{title}">'
                f'<figcaption><strong>{title}</strong> · {src_note}</figcaption></figure>')
        facets = []
        for iso in sorted(ISO_NAMES, key=ISO_NAMES.get):
            mm = S5_MONTH[season]
            s5 = ts["seas5"].get(f"{iso}|{season}|{mm}", {})
            mme = []
            for key, series in ts["osf"]["sadc-mme-full"].items():
                k_iso, k_seas, k_mm = key.split("|")
                if k_iso == iso and k_seas == season:
                    mme += [(y, v, k_mm) for y, v in series.items()]
            sub = cstats[(cstats.iso3 == iso) & (cstats.season == season)]
            newv, prior = None, []
            for _, r in sub.iterrows():
                # plot at ISSUE year — same convention as the SEAS5/MME series
                if r.vintage == "2026/27":
                    newv = float(r.wetlean)
                else:
                    prior.append((int(r.issued[:4]), float(r.wetlean), r.vintage))
            facets.append(facet_svg(iso, season, s5, mme, newv, prior))
        sections.append(f"""
  <section>
    <h2>{SEASON_LABEL[season]}</h2>
    <div class="maps">{''.join(figs)}</div>
    <div class="grid">{''.join(facets)}</div>
    <p class="note">SEAS5 line: issued month {S5_MONTH[season]}, percentile vs 1993–2022 climatology
      (large dot = the current 2026 issue{'' if season != 'JFM' else ' — not yet available for JFM from a September issue'}).
      Teal dots: archived CSC MME issues (all issue months, wet-lean 0–100). Filled magenta diamond: this
      SARCOF-33 consensus zone score; hollow magenta diamonds: prior years' consensus outlooks
      (digitized from the statement PDFs), plotted at their target year.</p>
  </section>""")

    legend = "".join(
        f'<span class="chip"><i style="background:rgb{PAL[c]}"></i>{CLASS_LABEL[c]}</span>' for c in PAL
    ) + f'<span class="chip"><i style="background:{S5_C}"></i>raw SEAS5</span>' \
        f'<span class="chip"><i style="background:{OSF_C}"></i>CSC MME archive</span>' \
        f'<span class="chip"><i style="background:{NEW_C}"></i>SARCOF-33 consensus</span>' \
        f'<span class="chip"><i style="background:#fff;border:1.5px solid {NEW_C}"></i>prior consensus vintages</span>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>SARCOF-33 outlook review</title>
<style>
  body {{ margin: 0; background: #fcfcfb; color: #0b0b0b; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 15px; line-height: 1.45; }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 18px; margin: 34px 0 10px; border-top: 1px solid #e1e0d9; padding-top: 18px; }}
  .warn {{ background: #fdf3e0; border: 1px solid #eachd; border-radius: 8px; padding: 10px 14px; font-size: 13.5px; margin: 14px 0; }}
  .maps {{ display: flex; gap: 12px; overflow-x: auto; align-items: flex-start; }}
  figure {{ margin: 0; flex: 0 0 auto; width: 265px; }}
  figure.wide {{ width: 430px; }}
  figure img {{ width: 100%; border: 1px solid #e1e0d9; border-radius: 6px; background: #fff; }}
  figure.hl img {{ border: 2px solid #b3266d; }}
  figcaption {{ font-size: 12px; color: #52514e; margin-top: 3px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px 16px; margin-top: 14px; }}
  .facet {{ background: #ffffff; border: 1px solid #e1e0d9; border-radius: 8px; padding: 6px 6px 2px; }}
  .facet h4 {{ margin: 0 0 2px 4px; font-size: 12px; }}
  .facet svg {{ width: 100%; display: block; }}
  .facet svg text {{ fill: #898781; font-size: 8.5px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
  .chip {{ display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: #52514e; }}
  .chip i {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
  .note {{ font-size: 12.5px; color: #52514e; }}
</style></head><body><main>
  <h1>SARCOF-33 seasonal outlook — 2026/27 rainfall season</h1>
  <p class="note">Digitized by OCHA CHD Data Science — SARCOF-33 from the official CSC presentation
    deck (26 Aug 2026), prior vintages (2017/18–2025/26, gaps 2018/19 &amp; 2022/23) from the official
    statement PDFs · grid 0.25°, class zones; dotted texture = high-confidence overlay (reliable for
    2026/27, detected from the clean official render). Per the statement legends each class is a
    tercile-probability triplet (A/N/B): Above-Normal 40/35/25, Normal-to-Above 35/40/25,
    Normal-to-Below 25/40/35, Below-Normal 25/35/40.</p>
  <div class="warn"><strong>Pre-release material.</strong> SARCOF-33 maps come from the official
    presentation deck delivered at the forum (26 Aug 2026); the final published statement may still
    differ. Please do not circulate this link further.</div>
  <div class="chips">{legend}</div>
  {''.join(sections)}
  <p class="note">Wet-lean scale: 50 = neutral; SEAS5 shown as climatological percentile; MME archive
    dots and the consensus diamond are absolute class/score mappings (±70 → 0/100 and ±50 → 14/86) —
    constructs differ, see ds-regional-forecasts CLAUDE.md. Built {pd.Timestamp.now():%Y-%m-%d}.</p>
</main></body></html>"""
    html = html.replace("#eachd", "#eecd8d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "sarcof33.html").write_text(html)
    logger.info(f"plaintext page: {OUT_DIR / 'sarcof33.html'} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
