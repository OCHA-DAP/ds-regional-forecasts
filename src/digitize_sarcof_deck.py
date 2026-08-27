"""Digitize the OFFICIAL SARCOF-33 presentation deck (received 2026-08-27),
superseding the cell-phone-photo digitization in digitize_sarcof_photos.py.

The deck ("SADC Regional Seasonal Outlook for the 2026/27 season", presented
26 Aug 2026, archived in data/raw/sadc/sarcof/2026/) carries the four "Merged
Regional Forecast with Confidence Overlay" maps (OND/NDJ/DJF 2026/27, JFM
2027) as clean rendered rasters — same 4-class scheme + high-confidence hatch
as the photos, so hatch detection is trustworthy here (unlike the photos).

The forecast map is the largest embedded image on each "Seasonal Outlook for
<season>" page (the smaller map-sized image is a CHIRPS climatology panel).
Georeferencing does NOT reuse the statement-fitter's edge-mask score: these
maps sit on an OSM basemap whose confidence-hatch texture the edge score
locks onto (OND), and they carry no graticule lines. Instead fit_map scores
coastline point pairs — offshore must hit the flat ocean fill, inland must
not — which the hatch texture cannot fake. NDJ/DJF/JFM images are cropped at
~11.5°E by the slide layout, clipping a sliver of the Angola coast; cells
that fall off-image are seam-filled from neighbors.

Output (data/processed/sarcof33/):
  sarcof33_official_digitized.nc   same schema as the photo file
  sarcof33_official_country_stats.parquet
  maps/<season>.png                the extracted official map images
  recons/<season>.png              digitization QA renders
Also prints per-season agreement vs the photo digitization.

Second entry point (`python -m src.digitize_sarcof_deck osf`): the deck's
GPC-outlook pages also embed the CSC's own MME tercile-PROBABILITY maps
(OND + NDJ 2026, issued Aug 2026, skill-masked "-m" variant) — the standard
OSF product, which csc.sadc.int has NOT published since 2026-Apr (probed:
drupalSettings and constructed URLs both 404). The deck copies are the only
available record, so they are digitized through digitize_osf's calibration
(upscaled back to the canonical 1500x1500 render size; the CSC map is the
only square embedded image on those pages). Kept OUT of raw/sadc/
osf-seasonal/ so a future grab of the real files is not blocked — natives
live beside the deck PDF in raw/sadc/sarcof/2026/osf-from-deck/, and the
digitization goes to a separate sarcof33_mme_osf.nc (+ country stats with
rank vs the MME01-masked record), not the canonical osf-digitized stacks.
"""

import logging
from pathlib import Path

import fitz
import numpy as np
import pandas as pd
import xarray as xr
from PIL import Image

from src.digitize_sarcof_photos import (
    CLASS_NAMES,
    DRYNESS,
    LATS,
    LONS,
    apply_h,
    land_and_masks,
)
from src.digitize_sarcof_statements import (
    classify_grid,
    recon_png,
    solve_h,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
PDF = ROOT / "data" / "raw" / "sadc" / "sarcof" / "2026" / "SARCOF-33_Regional_Seasonal_Outlook_2026-27_presentation.pdf"
OUT = ROOT / "data" / "processed" / "sarcof33"

SEASONS = ["OND", "NDJ", "DJF", "JFM"]

OCEAN = np.array([171, 210, 225])  # flat ocean fill, identical in all four maps


def coast_pairs(offset=0.35):
    """(inland, offshore) lon/lat point pairs straddling the SADC coastline.

    The deck maps carry no graticule lines and the statement-fitter's
    edge-mask score locks onto the confidence-hatch texture (OND) — but the
    ocean fill is a single flat color, so requiring offshore=ocean AND
    inland=not-ocean across the coast is unambiguous. Coast-ness of each
    exterior-outline point is decided against the all-Africa land union.
    """
    import json

    from shapely import contains_xy
    from shapely.geometry import polygon as spoly, shape
    from shapely.ops import unary_union

    gj = json.loads((ROOT / "data" / "tmp" / "sadc_continental.geojson").read_text())
    union = unary_union([shape(f["geometry"]) for f in gj["features"]]).simplify(0.05)
    afr = json.loads((ROOT / "data" / "tmp" / "African_States.geojson").read_text())
    from shapely import make_valid
    # simplify BEFORE the union — buffering/unioning the full-detail
    # all-Africa geometry eats several GB of RAM
    land_all = unary_union(
        [make_valid(shape(f["geometry"])).simplify(0.02) for f in afr["features"]]
    )
    geoms = union.geoms if union.geom_type == "MultiPolygon" else [union]
    inland, offshore = [], []
    for poly in geoms:
        ring = np.array(spoly.orient(poly).exterior.coords)  # CCW: outward = (dy, -dx)
        for i in range(len(ring) - 1):
            a, b = ring[i], ring[i + 1]
            seg = b - a
            n = max(1, int(np.hypot(*seg) / 0.15))
            nrm = np.array([seg[1], -seg[0]]) / max(np.hypot(*seg), 1e-9)
            for t in np.linspace(0, 1, n, endpoint=False):
                p = a + t * seg
                if not contains_xy(land_all, *(p + nrm * offset)):
                    inland.append(p - nrm * offset)
                    offshore.append(p + nrm * offset)
    return np.array(inland)[::2], np.array(offshore)[::2]


def fit_map(im, inland, offshore):
    """Affine seed by FFT correlation against the ocean mask, then the
    statement-fitter's corner-perturbation homography refinement with an
    ocean-pair score."""
    Hh, Ww = im.shape[:2]
    ocean = np.abs(im - OCEAN).max(axis=2) <= 10

    def score(H):
        pin, pout = apply_h(H, inland), apply_h(H, offshore)
        ixi, iyi = pin[:, 0].round().astype(int), pin[:, 1].round().astype(int)
        ixo, iyo = pout[:, 0].round().astype(int), pout[:, 1].round().astype(int)
        ok = ((ixi >= 0) & (ixi < Ww) & (iyi >= 0) & (iyi < Hh)
              & (ixo >= 0) & (ixo < Ww) & (iyo >= 0) & (iyo < Hh))
        if ok.mean() < 0.75:
            return 0.0
        return (ocean[iyo[ok], ixo[ok]] & ~ocean[iyi[ok], ixi[ok]]).mean()

    o2 = ocean[::2, ::2].astype(np.float32)
    Hm, Wm = o2.shape
    Fo = np.fft.rfft2(o2)
    Fl = np.fft.rfft2(1.0 - o2)
    lon0, lat1 = inland[:, 0].min(), inland[:, 1].max()
    best = (-1, None)
    for s in np.arange(8.0, 14.01, 0.25):  # half-res px/deg
        B_off = np.zeros_like(o2)
        B_in = np.zeros_like(o2)
        for pts, B in ((offshore, B_off), (inland, B_in)):
            ix = ((pts[:, 0] - lon0) * s).round().astype(int)
            iy = ((lat1 - pts[:, 1]) * s).round().astype(int)
            ok = (ix >= 0) & (ix < Wm) & (iy >= 0) & (iy < Hm)
            B[iy[ok], ix[ok]] += 1
        corr = (np.fft.irfft2(Fo * np.conj(np.fft.rfft2(B_off)), s=o2.shape)
                + np.fft.irfft2(Fl * np.conj(np.fft.rfft2(B_in)), s=o2.shape))
        k = int(np.argmax(corr))
        ty, tx = divmod(k, Wm)
        if corr.max() > best[0]:
            best = (corr.max(), (s * 2, tx * 2, ty * 2))
    _, (s, tx, ty) = best
    H = np.array([[s, 0, tx - lon0 * s], [0, -s, ty + lat1 * s], [0, 0, 1.0]])
    ref = np.array([(12, -35), (52, -35), (12, -4), (52, -4)], float)
    corners = apply_h(H, ref)
    step = 12.0
    while step >= 0.5:
        improved = False
        for ci in range(4):
            for d in [(step, 0), (-step, 0), (0, step), (0, -step),
                      (step, step), (-step, -step), (step, -step), (-step, step)]:
                cand = corners.copy()
                cand[ci] += d
                if score(solve_h(ref, cand)) > score(solve_h(ref, corners)):
                    corners = cand
                    improved = True
        if not improved:
            step /= 2
    H = solve_h(ref, corners)
    return H, score(H)


def forecast_images(doc):
    """(season, RGB array) for each 'Seasonal Outlook for <season>' page —
    the forecast map is the largest embedded image on the page."""
    import re

    rx = re.compile(r"Seasonal Outlook for (OND|NDJ|DJF|JFM)")
    for page in doc:
        m = rx.search(page.get_text()[:200])
        if not m:
            continue
        best = max(page.get_images(full=True), key=lambda x: x[2] * x[3])
        pix = fitz.Pixmap(doc, best[0])
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., : 3]
        yield m.group(1), arr


def main() -> None:
    land, country = land_and_masks()
    inland, offshore = coast_pairs()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "maps").mkdir(exist_ok=True)
    (OUT / "recons").mkdir(exist_ok=True)

    doc = fitz.open(PDF)
    classes = {}
    confs = {}
    for season, im in forecast_images(doc):
        Image.fromarray(im.astype(np.uint8)).save(OUT / "maps" / f"{season}.png")
        # slide-layout crops (JFM loses everything west of ~12.3°E) push coast
        # pairs off-image and strand the fit at score 0 — pad with white so
        # every pair lands somewhere (pad classifies as 0 -> seam-filled)
        im = np.pad(im, ((250, 250), (250, 250), (0, 0)), constant_values=255).astype(int)
        H, s = fit_map(im, inland, offshore)
        cls, conf = classify_grid(im.astype(int), H, land)
        vals, cnts = np.unique(cls, return_counts=True)
        logger.info(f"{season}: fit {s:.2f} | {dict(zip(vals.tolist(), cnts.tolist()))}")
        recon_png(cls, conf, OUT / "recons" / f"{season}.png")
        classes[season], confs[season] = cls, conf
    missing = [s for s in SEASONS if s not in classes]
    if missing:
        raise RuntimeError(f"seasons not found in deck: {missing}")

    ds = xr.Dataset(
        {
            "clazz": (("season", "lat", "lon"), np.stack([classes[s] for s in SEASONS])),
            "confidence": (("season", "lat", "lon"), np.stack([confs[s] for s in SEASONS])),
        },
        coords={"season": SEASONS, "lat": LATS, "lon": LONS},
        attrs={
            "title": "SARCOF-33 merged regional (consensus) outlook, digitized from the official presentation deck",
            "issued": "2026-08 (SARCOF-33 annual forum, presented 26 Aug 2026)",
            "source": str(PDF.relative_to(ROOT / "data" / "raw")) + " (official CSC deck; final statement may still differ)",
            "class_codes": "-1 outside SADC, 0 unknown, 1 Below-Normal, 2 Normal-to-Below, 3 Normal-to-Above, 4 Above-Normal",
            "confidence_note": "high-confidence hatch overlay detected from the clean render — reliable, unlike the photo digitization",
            "method": "boundary-fitted homography + hue-rule classification; src/digitize_sarcof_deck.py",
        },
    )
    ds.to_netcdf(OUT / "sarcof33_official_digitized.nc",
                 encoding={"clazz": {"zlib": True, "complevel": 4}})
    logger.info(f"wrote {OUT}/sarcof33_official_digitized.nc")

    # agreement vs the photo digitization (same forecast -> should be high)
    ph = xr.open_dataset(OUT / "sarcof33_photo_digitized.nc")
    for season in SEASONS:
        a = classes[season]
        b = ph.sel(season=season)["clazz"].values
        both = (a > 0) & (b > 0)
        logger.info(f"{season}: photo-vs-official class agreement "
                    f"{(a[both] == b[both]).mean():.1%} over {int(both.sum())} cells")

    rows = []
    for season in SEASONS:
        c, cf = classes[season], confs[season]
        for iso, m in country.items():
            mm = m & (c > 0)
            if mm.sum() == 0:
                continue
            cc = c[mm]
            rows.append({
                "iso3": iso, "season": season, "n_cells": int(mm.sum()),
                **{f"frac_{n}": float((cc == k).mean()) for k, n in CLASS_NAMES.items()},
                "dryness_score": float(sum(DRYNESS[k] * (cc == k).mean() for k in DRYNESS)),
                "frac_confident": float(cf[mm].mean()),
            })
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "sarcof33_official_country_stats.parquet", index=False)
    logger.info("\n" + df.pivot(index="iso3", columns="season", values="dryness_score").round(0).to_string())


OSF_RAW = ROOT / "data" / "raw" / "sadc" / "sarcof" / "2026" / "osf-from-deck"


def deck_osf_images(doc):
    """(season, RGB array) for the CSC MME probability map on each
    GPC-outlook page — the only square embedded image there (the WMO/other
    GPC panels are not square)."""
    import re

    rx = re.compile(r"Global Producing Centre.{0,80}?(OND|NDJ|DJF|JFM)", re.S)
    for page in doc:
        m = rx.search(page.get_text()[:300])
        if not m:
            continue
        for info in page.get_images(full=True):
            xref, w, h = info[0], info[2], info[3]
            if w < 700 or w != h:
                continue
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., : 3]
            yield m.group(1), arr


def main_osf() -> None:
    from src.digitize_osf import LATS as OLATS
    from src.digitize_osf import LONS as OLONS
    from src.digitize_osf import digitize_image
    from src.osf_country_stats import country_masks, slice_stats

    OSF_RAW.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    res = {}
    for season, arr in deck_osf_images(doc):
        native = Image.fromarray(arr.astype(np.uint8))
        native.save(OSF_RAW / f"PRCP_prob-tercile-m_MME01_2026-Aug_{season}.png")
        tf = ROOT / "data" / "tmp" / f"deck_osf_{season}.png"
        native.resize((1500, 1500), Image.LANCZOS).save(tf)
        terc, plb = digitize_image(tf, "PRCP")
        tf.unlink()
        n_bad = int((terc == -1).sum())
        logger.info(f"{season}: signal {int((terc > 0).sum())} cells, no-signal {int((terc == 0).sum())}, "
                    f"unclassified/logo {n_bad}")
        res[season] = (terc, plb)
    if not res:
        raise RuntimeError("no CSC MME probability maps found in the deck")

    seasons = list(res)
    ds = xr.Dataset(
        {
            "tercile": (("season", "lat", "lon"), np.stack([res[s][0] for s in seasons])),
            "prob_lb": (("season", "lat", "lon"), np.stack([res[s][1] for s in seasons])),
        },
        coords={"season": seasons, "lat": OLATS, "lon": OLONS},
        attrs={
            "title": "CSC MME tercile-probability forecast (skill-masked), digitized from the SARCOF-33 official deck",
            "issued": "2026-08",
            "source": "official presentation deck, 26 Aug 2026 — csc.sadc.int has not published OSF issues past 2026-04, "
                      "so the deck-embedded renders (downscaled by the slide layout, upscaled back to 1500px) are the only record",
            "codes": "tercile -1 unrecoverable, 0 no-signal/masked, 1 below, 2 normal, 3 above; prob_lb = probability class lower bound",
            "method": "src/digitize_sarcof_deck.py main_osf() via digitize_osf calibration",
        },
    )
    ds.to_netcdf(OUT / "sarcof33_mme_osf.nc", encoding={"tercile": {"zlib": True, "complevel": 4}})
    logger.info(f"wrote {OUT}/sarcof33_mme_osf.nc")

    masks = country_masks(OLATS, OLONS)
    rec = pd.read_parquet(ROOT / "data" / "processed" / "osf-digitized" / "osf_country_stats.parquet")
    rec = rec[(rec.system == "MME01") & rec.skill_masked]
    rows = []
    for season in seasons:
        terc, plb = res[season]
        for iso, m in masks.items():
            st = slice_stats(terc, plb, m)
            if st is None:
                continue
            rd = rec[(rec.iso3 == iso) & (rec.season == season)]["dryness_score"]
            rows.append({
                "iso3": iso, "season": season, **st,
                "pct_record_drier": float(round(100 * (rd > st["dryness_score"]).mean())) if len(rd) else np.nan,
                "n_record": len(rd),
            })
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "sarcof33_mme_osf_country_stats.parquet", index=False)
    logger.info("\ndryness (pct of record drier):\n" + df.assign(
        s=lambda d: d.dryness_score.round(0).astype(int).astype(str) + " (" + d.pct_record_drier.fillna(-1).astype(int).astype(str) + "%)"
    ).pivot(index="iso3", columns="season", values="s").to_string())


if __name__ == "__main__":
    import sys

    main_osf() if "osf" in sys.argv[1:] else main()
