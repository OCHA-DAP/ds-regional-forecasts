"""Digitize the consensus outlook maps inside archived SARCOF statement PDFs.

Every main-forum statement carries the same 4-class merged consensus maps
(Below-Normal / Normal-to-Below / Normal-to-Above / Above-Normal, each with
a fixed tercile-probability triplet in the legend: 25/35/40 family). This
recovers them onto the standard 0.25-degree grid for every archived vintage
and merges the SARCOF-33 photo digitization (src/digitize_sarcof_photos.py)
into one consensus record.

Vintages: SARCOF-21 (2017/18), 23 (2019/20), 24 (2020/21), 25 (2021/22),
27 (2023/24), 29 (2024/25), 31 (2025/26), 33 (2026/27, photos).
Gaps: 2018/19 and 2022/23 (the SARCOF-22 and -26 statements are lost);
JFM maps only exist where the forum drew them (23, 24, 25, 33).

Georeferencing: same approach as the photo digitizer — a homography fitted
by maximizing overlap of the SADC union's exterior outline with saturated/
background transitions, seeded by FFT cross-correlation. PDF pages are flat,
so fits are tight; every map's boundary-overlap score is logged and a recon
PNG is written for QA.

Output: data/processed/sarcof-consensus/sarcof_consensus.nc
        dims (vintage, season, lat, lon); class codes as in the photo module.
        + per-country stats/extremeness parquet.
"""

import json
import logging
import re
from pathlib import Path

import fitz
import numpy as np
import pandas as pd
import xarray as xr
from PIL import Image

from src.digitize_sarcof_photos import (
    CLASS_NAMES,
    DRYNESS,
    ISO3,
    LATS,
    LONS,
    apply_h,
    classify_rgb,
    land_and_masks,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
OUT = ROOT / "data" / "processed" / "sarcof-consensus"

# (statement pdf, vintage label, issued YYYY-MM)
SOURCES = [
    ("data/raw/sadc/sarcof/2017/SARCOF_21_Statement.pdf", "2017/18", "2017-08"),
    ("data/raw/sadc/sarcof/2019/SARCOF-23_STATEMENT.pdf", "2019/20", "2019-08"),
    ("data/raw/sadc/sarcof/2020/FINAL_SARCOF-24_STATEMENT.pdf", "2020/21", "2020-08"),
    ("data/raw/sadc/sarcof/2021/EN_FINAL-SARCOF-25-STATEMENT-for-2021-22-rainfall-season.pdf", "2021/22", "2021-09"),
    ("data/raw/sadc/sarcof/2023/FINAL_SARCOF-27_STATEMENT.pdf", "2023/24", "2023-09"),
    ("data/raw/sadc/sarcof/2024/EN_FINAL_SARCOF-29_STATEMENT.pdf", "2024/25", "2024-08"),
    ("data/raw/sadc/sarcof/2025/FINAL_SARCOF-31_STATEMENT.pdf", "2025/26", "2025-09"),
]

SEASON_RES = [
    ("JFM", re.compile(r"JANUARY[\s\-–]*FEBRUARY[\s\-–]*MARCH", re.I)),
    ("DJF", re.compile(r"DECEMBER[\s\d,\-–]*JANUARY[\s\-–]*FEBRUARY", re.I)),
    ("NDJ", re.compile(r"NOVEMBER[\s\-–]*DECEMBER[\s\d,\-–]*JANUARY", re.I)),
    ("OND", re.compile(r"OCTOBER[\s\-–]*NOVEMBER[\s\-–]*DECEMBER", re.I)),
]

# legend probability triplets (A, N, B) per class — constant across statements
PROB_TRIPLETS = {1: (25, 35, 40), 2: (25, 40, 35), 3: (35, 40, 25), 4: (40, 35, 25)}

SEASONS_ALL = ["OND", "NDJ", "DJF", "JFM"]


def boundary_pts():
    from shapely.geometry import shape
    from shapely.ops import unary_union

    gj = json.loads((ROOT / "data" / "tmp" / "sadc_continental.geojson").read_text())
    union = unary_union([shape(f["geometry"]) for f in gj["features"]]).simplify(0.05)
    geoms = union.geoms if union.geom_type == "MultiPolygon" else [union]
    pts = []
    for poly in geoms:
        ring = np.array(poly.exterior.coords)
        for i in range(len(ring) - 1):
            a, b = ring[i], ring[i + 1]
            n = max(1, int(np.hypot(*(b - a)) / 0.15))
            for t in np.linspace(0, 1, n, endpoint=False):
                pts.append(a + t * (b - a))
    return np.array(pts)[::2]


def edge_mask(im):
    c = im.astype(int)
    mx, mn = c.max(axis=2), c.min(axis=2)
    sat = (mx - mn > 38) | ((c[..., 2] > 110) & (c[..., 2] - c[..., 0] > 50))
    m = np.zeros_like(sat)
    for sh in range(1, 4):
        m[sh:] |= sat[sh:] != sat[:-sh]
        m[:-sh] |= sat[:-sh] != sat[sh:]
        m[:, sh:] |= sat[:, sh:] != sat[:, :-sh]
        m[:, :-sh] |= sat[:, :-sh] != sat[:, sh:]
    return m


def solve_h(src, dst):
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, V = np.linalg.svd(np.array(A))
    return V[-1].reshape(3, 3)


def fit_page(im, bpts):
    Hh, Ww = im.shape[:2]
    mask = edge_mask(im)

    def score(H):
        px = apply_h(H, bpts)
        ix, iy = px[:, 0].round().astype(int), px[:, 1].round().astype(int)
        ok = (ix >= 0) & (ix < Ww) & (iy >= 0) & (iy < Hh)
        if ok.mean() < 0.9:
            return 0.0
        return mask[iy[ok], ix[ok]].mean()

    # FFT seed over a scale grid at half resolution
    m2 = mask[::2, ::2].astype(np.float32)
    Hm, Wm = m2.shape
    F = np.fft.rfft2(m2)
    best = (-1, None)
    for sx in np.arange(4.0, 14.01, 0.5):
        for sy in np.arange(4.0, 14.01, 0.5):
            px = (bpts[:, 0] - bpts[:, 0].min()) * sx
            py = (bpts[:, 1].max() - bpts[:, 1]) * sy
            B = np.zeros_like(m2)
            ix, iy = px.round().astype(int), py.round().astype(int)
            ok = (ix < Wm) & (iy < Hm)
            B[iy[ok], ix[ok]] += 1
            corr = np.fft.irfft2(F * np.conj(np.fft.rfft2(B)), s=m2.shape)
            k = int(np.argmax(corr))
            ty, tx = divmod(k, Wm)
            s = corr.max() / len(bpts)
            if s > best[0]:
                best = (s, (sx * 2, sy * 2, tx * 2, ty * 2))
    _, (sx, sy, tx, ty) = best
    H = np.array([[sx, 0, tx - bpts[:, 0].min() * sx],
                  [0, -sy, ty + bpts[:, 1].max() * sy],
                  [0, 0, 1.0]])
    # corner-perturbation refinement
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


def classify_grid(im, H, land):
    Hh, Ww = im.shape[:2]
    cls = np.zeros((len(LATS), len(LONS)), dtype=np.int8)
    conf_frac = np.zeros_like(cls, dtype=float)
    offs = [(dx, dy) for dx in (-0.07, 0, 0.07) for dy in (-0.07, 0, 0.07)]
    dense = [(dx, dy) for dx in np.linspace(-0.1, 0.1, 5) for dy in np.linspace(-0.1, 0.1, 5)]
    for j, lat in enumerate(LATS):
        for i, lon in enumerate(LONS):
            if not land[j, i]:
                cls[j, i] = -1
                continue
            pts = apply_h(H, np.array([(lon + dx, lat + dy) for dx, dy in offs]))
            ix, iy = pts[:, 0].round().astype(int), pts[:, 1].round().astype(int)
            ok = (ix >= 0) & (ix < Ww) & (iy >= 0) & (iy < Hh)
            if ok.sum() < 5:
                continue
            samp = im[iy[ok], ix[ok]]
            lum = samp.sum(axis=1)
            keep = samp[lum >= np.quantile(lum, 0.4)]
            cls[j, i] = classify_rgb(*np.median(keep, axis=0))
            dpts = apply_h(H, np.array([(lon + dx, lat + dy) for dx, dy in dense]))
            dix, diy = dpts[:, 0].round().astype(int), dpts[:, 1].round().astype(int)
            dok = (dix >= 0) & (dix < Ww) & (diy >= 0) & (diy < Hh)
            ds = im[diy[dok], dix[dok]].sum(axis=1)
            conf_frac[j, i] = (ds < np.median(ds) * 0.80).mean()

    def win(j, i):
        return cls[max(0, j - 2): j + 3, max(0, i - 2): i + 3]

    for _ in range(2):
        for j, i in zip(*np.nonzero(cls == 0)):
            w = win(j, i)
            vals, cnts = np.unique(w[w > 0], return_counts=True)
            if len(vals) and cnts.max() >= 6:
                cls[j, i] = vals[np.argmax(cnts)]
    for j, i in zip(*np.nonzero(cls > 0)):
        w = win(j, i)
        others = w[(w > 0) & (w != cls[j, i])]
        pos = (w > 0).sum() - 1
        if pos >= 10 and len(others) >= 0.8 * pos:
            vals, cnts = np.unique(others, return_counts=True)
            cls[j, i] = vals[np.argmax(cnts)]
    pad = np.pad(conf_frac, 2, mode="edge")
    sm = sum(pad[dj: dj + cls.shape[0], di: di + cls.shape[1]] for dj in range(5) for di in range(5)) / 25
    return cls, (sm > 0.10) & (cls > 0)


PAL = {1: (198, 156, 109), 2: (238, 221, 57), 3: (64, 189, 176), 4: (28, 32, 199)}


def recon_png(cls, conf, dest: Path):
    rec = np.full((cls.shape[0] * 4, cls.shape[1] * 4, 3), 255, np.uint8)
    for code, col in PAL.items():
        rec[np.kron(cls == code, np.ones((4, 4), bool))] = col
    yy, xx = np.mgrid[0: rec.shape[0], 0: rec.shape[1]]
    rec[np.kron(conf, np.ones((4, 4), bool)) & (yy % 6 == 0) & (xx % 6 == 0)] = (60, 60, 60)
    Image.fromarray(rec).save(dest)


def main() -> None:
    land, country = land_and_masks()
    bpts = boundary_pts()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "recons").mkdir(exist_ok=True)

    MIN_FIT = 0.70  # below this the georeference is untrustworthy -> drop

    def candidate_rasters(doc, pi):
        """Full-page render plus each map-sized embedded image (multi-map
        pages embed each map as its own xref; fitting the standalone raster
        dodges the neighbors)."""
        page = doc[pi]
        zoom = 1500 / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        yield np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(int)
        for info in page.get_images(full=True):
            xref, w, h = info[0], info[2], info[3]
            if w < 800 or h < 500 or not 0.5 < w / h < 2.2:
                continue
            try:
                p2 = fitz.Pixmap(doc, xref)
                if p2.n - p2.alpha > 3:
                    p2 = fitz.Pixmap(fitz.csRGB, p2)
                arr = np.frombuffer(p2.samples, np.uint8).reshape(p2.height, p2.width, p2.n)[..., :3]
                if max(p2.width, p2.height) > 2200:  # keep fits fast
                    im2 = Image.fromarray(arr)
                    im2.thumbnail((2000, 2000))
                    arr = np.asarray(im2)
                yield arr.astype(int)
            except Exception:
                continue

    vintages, cubes, confs_all = [], [], []
    for path, vintage, issued in SOURCES:
        doc = fitz.open(ROOT / path)
        found: dict[str, int] = {}
        for pi, page in enumerate(doc):
            if not any(x[2] > 500 and x[3] > 400 for x in page.get_images(full=True)):
                continue
            # window covers headings that sit below a previous section's
            # zone list (e.g. SARCOF-21's JFM heading at char ~430)
            txt = page.get_text()[:1000]
            if re.search(r"LONG[\s\-–]*TERM|CLIMATOLOG", txt, re.I):
                continue  # climatology figure pages caption their JFM/OND months too
            for season, rx in SEASON_RES:
                if season not in found and rx.search(txt):
                    found[season] = pi
                    break
        cube = np.full((len(SEASONS_ALL), len(LATS), len(LONS)), -1, np.int8)
        confc = np.zeros_like(cube, dtype=bool)
        for season, pi in found.items():
            best = (-1.0, None, None)
            for im in candidate_rasters(doc, pi):
                H, s = fit_page(im, bpts)
                if s > best[0]:
                    best = (s, H, im)
            s, H, im = best
            if s < MIN_FIT:
                logger.warning(f"{vintage} {season} (p{pi + 1}): best fit {s:.2f} < {MIN_FIT} — dropped")
                continue
            cls, conf = classify_grid(im, H, land)
            si = SEASONS_ALL.index(season)
            cube[si], confc[si] = cls, conf
            vals, cnts = np.unique(cls, return_counts=True)
            logger.info(f"{vintage} {season} (p{pi + 1}): fit {s:.2f} | {dict(zip(vals.tolist(), cnts.tolist()))}")
            recon_png(cls, conf, OUT / "recons" / f"{vintage.replace('/', '-')}_{season}.png")
        vintages.append((vintage, issued))
        cubes.append(cube)
        confs_all.append(confc)

    # merge SARCOF-33 photo digitization as the 2026/27 vintage
    ph = xr.open_dataset(ROOT / "data" / "processed" / "sarcof33" / "sarcof33_photo_digitized.nc")
    cube = np.full((len(SEASONS_ALL), len(LATS), len(LONS)), -1, np.int8)
    confc = np.zeros_like(cube, dtype=bool)
    for si, season in enumerate(SEASONS_ALL):
        sel = ph.sel(season=season)
        cube[si] = sel["clazz"].values
        confc[si] = sel["confidence"].values
        recon_png(cube[si], confc[si], OUT / "recons" / f"2026-27_{season}.png")
    vintages.append(("2026/27", "2026-08"))
    cubes.append(cube)
    confs_all.append(confc)

    ds = xr.Dataset(
        {
            "clazz": (("vintage", "season", "lat", "lon"), np.stack(cubes)),
            "confidence": (("vintage", "season", "lat", "lon"), np.stack(confs_all)),
        },
        coords={
            "vintage": [v for v, _ in vintages],
            "issued": ("vintage", [i for _, i in vintages]),
            "season": SEASONS_ALL,
            "lat": LATS, "lon": LONS,
        },
        attrs={
            "title": "SARCOF consensus outlooks digitized from statement PDFs (+ 2026/27 forum photos)",
            "class_codes": "-1 outside SADC / no map, 0 unknown, 1 Below-Normal, 2 Normal-to-Below, 3 Normal-to-Above, 4 Above-Normal",
            "probability_triplets": json.dumps({CLASS_NAMES[k]: v for k, v in PROB_TRIPLETS.items()})
            + " (A/N/B percent, per the statement legends)",
            "gaps": "2018/19 and 2022/23 statements lost; JFM only where drawn (2019/20, 2020/21, 2021/22, 2026/27)",
            "confidence_note": "hatch overlay exists only from 2024/25 on; detection experimental",
            "method": "src/digitize_sarcof_statements.py",
        },
    )
    ds.to_netcdf(OUT / "sarcof_consensus.nc", encoding={"clazz": {"zlib": True, "complevel": 4}})
    logger.info(f"wrote {OUT}/sarcof_consensus.nc")

    rows = []
    for vi, (vintage, issued) in enumerate(vintages):
        for si, season in enumerate(SEASONS_ALL):
            c = cubes[vi][si]
            if (c >= 0).sum() == 0:
                continue
            for iso, m in country.items():
                mm = m & (c > 0)
                if mm.sum() == 0:
                    continue
                cc = c[mm]
                rows.append({
                    "vintage": vintage, "issued": issued, "iso3": iso, "season": season,
                    "n_cells": int(mm.sum()),
                    **{f"frac_{n}": float((cc == k).mean()) for k, n in CLASS_NAMES.items()},
                    "dryness_score": float(sum(DRYNESS[k] * (cc == k).mean() for k in DRYNESS)),
                })
    df = pd.DataFrame(rows)
    grp = df.groupby(["iso3", "season"])
    df["dry_rank"] = grp["dryness_score"].rank(ascending=False, method="min").astype(int)
    df["n_vintages"] = grp["dryness_score"].transform("count")
    df.to_parquet(OUT / "sarcof_consensus_country_stats.parquet", index=False)
    latest = df[df.vintage == "2026/27"]
    logger.info("\n2026/27 dryness rank among consensus vintages (1 = driest):\n" +
                latest.pivot(index="iso3", columns="season", values="dry_rank").to_string() +
                "\nof n vintages:\n" +
                latest.pivot(index="iso3", columns="season", values="n_vintages").to_string())


if __name__ == "__main__":
    main()
