"""Digitize the SARCOF-33 (Aug 2026) consensus outlook maps from cell-phone
photos of the forum slides — the only record until the CSC publishes.

The slides show the "Merged Regional Forecast with Confidence Overlay":
4-class consensus zones (Below-Normal, Normal-to-Below, Normal-to-Above,
Above-Normal) plus a diagonal-hatch high-confidence overlay, for OND 2026,
NDJ 2026/27, DJF 2026/27 and JFM 2027.

Method: photo -> lon/lat homography fitted by maximizing the overlap of the
SADC union's exterior outline with saturated-zone/background transitions in
the photo (seeded by FFT cross-correlation over a scale grid; the fitting
code lives in the 2026-08 session scratchpad and the resulting matrices are
frozen below). Classification: per 0.25-degree cell, median photo color over
a 3x3 lon/lat jitter (darkest 40% of samples dropped to dodge hatch lines and
borders), classified by hue rules; zone-boundary seams neighbor-majority
filled; speckles majority-cleaned. Confidence hatch detection (dark-sample
fraction, 5x5-cell smoothed) is EXPERIMENTAL — cells are only ~4 photo px.

Output: data/processed/sarcof33/sarcof33_photo_digitized.nc
  class: -1 outside SADC, 0 unknown, 1 Below-Normal, 2 Normal-to-Below,
         3 Normal-to-Above, 4 Above-Normal
  confidence: bool (experimental)
Plus per-country stats printed and saved (dryness score convention:
class -> +50/+25/-25/-50, comparable in spirit to the OSF dryness score).
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
PHOTOS = ROOT / "data" / "raw" / "sadc" / "sarcof33-photos"
OUT = ROOT / "data" / "processed" / "sarcof33"

LONS = np.arange(10.125, 52.1251, 0.25)
LATS = np.arange(7.875, -37.3751, -0.25)

SEASONS = {"ond2026": "OND", "ndj2026": "NDJ", "djf2026": "DJF", "jfm2027": "JFM"}

# lon/lat -> photo pixel homographies (boundary-fitted, 2026-08-26)
HOMOGRAPHIES = {
    "ond2026": [[8.8546281, -0.01056774, 159.88111], [-1.2781188, -10.479072, 570.04634], [-0.0016477772, 0.00030621326, 1]],
    "ndj2026": [[14.691924, -0.043076996, -65.502312], [1.571269, -14.087188, 416.76618], [0.0016529525, 0.00049475217, 1]],
    "djf2026": [[12.805934, -0.011249528, 59.908162], [0.99003443, -12.834039, 632.77495], [0.0010093743, -5.3309399e-05, 1]],
    "jfm2027": [[14.944299, -0.29758869, -63.68455], [1.246876, -15.033863, 583.51504], [0.0015524397, -1.4878104e-05, 1]],
}

CLASS_NAMES = {1: "below", 2: "normal-below", 3: "normal-above", 4: "above"}
DRYNESS = {1: 50.0, 2: 25.0, 3: -25.0, 4: -50.0}

ISO3 = {
    "Angola": "AGO", "Democratic Republic of the Congo": "COD", "Madagascar": "MDG",
    "Mozambique": "MOZ", "Malawi": "MWI", "South Africa": "ZAF", "Lesotho": "LSO",
    "Botswana": "BWA", "United Republic of Tanzania": "TZA", "Namibia": "NAM",
    "Swaziland": "SWZ", "Zambia": "ZMB", "Zimbabwe": "ZWE",
}


def classify_rgb(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    if b > 100 and b - r > 55 and b - g > 40:
        return 4
    if r > 130 and g > 120 and r + g - 2 * b > 110 and abs(r - g) < 70:
        return 2
    if g > 90 and g - r > 30 and b > r and g - b < 70:
        return 3
    if r > 110 and r - b > 20 and r > g > b * 0.9 and mx - mn > 18 and r - g < 70:
        return 1
    return 0


def apply_h(H, pts):
    p = np.c_[pts, np.ones(len(pts))] @ np.asarray(H).T
    return p[:, :2] / p[:, 2:3]


def land_and_masks():
    from shapely import contains_xy
    from shapely.geometry import shape
    from shapely.ops import unary_union

    gj = json.loads((ROOT / "data" / "tmp" / "sadc_continental.geojson").read_text())
    xx, yy = np.meshgrid(LONS, LATS)
    union = unary_union([shape(f["geometry"]) for f in gj["features"]]).buffer(0.02)
    land = contains_xy(union, xx.ravel(), yy.ravel()).reshape(xx.shape)
    country = {}
    for f in gj["features"]:
        iso = ISO3[f["properties"]["NAME"]]
        geom = shape(f["geometry"]).buffer(0.02)
        country[iso] = contains_xy(geom, xx.ravel(), yy.ravel()).reshape(xx.shape)
    return land, country


def digitize(key: str, land: np.ndarray):
    im = np.asarray(Image.open(PHOTOS / f"{key}.png").convert("RGB")).astype(int)
    Hh, Ww = im.shape[:2]
    H = HOMOGRAPHIES[key]
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

    # 1) fill unknown seam cells from a clear neighbor majority
    for _ in range(2):
        for j, i in zip(*np.nonzero(cls == 0)):
            w = win(j, i)
            vals, cnts = np.unique(w[w > 0], return_counts=True)
            if len(vals) and cnts.max() >= 6:
                cls[j, i] = vals[np.argmax(cnts)]
    # 2) flip speckles: a classified cell whose positive neighbors
    #    overwhelmingly (>=80%) agree on a different class
    for j, i in zip(*np.nonzero(cls > 0)):
        w = win(j, i)
        others = w[(w > 0) & (w != cls[j, i])]
        pos = (w > 0).sum() - 1
        if pos >= 10 and len(others) >= 0.8 * pos:
            vals, cnts = np.unique(others, return_counts=True)
            cls[j, i] = vals[np.argmax(cnts)]
    pad = np.pad(conf_frac, 2, mode="edge")
    sm = sum(pad[dj: dj + cls.shape[0], di: di + cls.shape[1]] for dj in range(5) for di in range(5)) / 25
    conf = (sm > 0.10) & (cls > 0)
    return cls, conf


def main() -> None:
    land, country = land_and_masks()
    classes, confs = [], []
    for key in SEASONS:
        c, cf = digitize(key, land)
        vals, cnts = np.unique(c, return_counts=True)
        logger.info(f"{key}: {dict(zip(vals.tolist(), cnts.tolist()))}")
        classes.append(c)
        confs.append(cf)

    ds = xr.Dataset(
        {
            "clazz": (("season", "lat", "lon"), np.stack(classes)),
            "confidence": (("season", "lat", "lon"), np.stack(confs)),
        },
        coords={"season": list(SEASONS.values()), "lat": LATS, "lon": LONS},
        attrs={
            "title": "SARCOF-33 merged regional (consensus) outlook, digitized from forum-slide photos",
            "issued": "2026-08 (SARCOF-33 annual forum)",
            "source": "cell-phone photos of the presented slides — pre-publication, verify against the official statement when released",
            "class_codes": "-1 outside SADC, 0 unknown, 1 Below-Normal, 2 Normal-to-Below, 3 Normal-to-Above, 4 Above-Normal",
            "confidence_note": "EXPERIMENTAL hatch detection; treat as indicative only",
            "method": "boundary-fitted homography + hue-rule classification; src/digitize_sarcof_photos.py",
        },
    )
    OUT.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT / "sarcof33_photo_digitized.nc",
                 encoding={"clazz": {"zlib": True, "complevel": 4}})
    logger.info(f"wrote {OUT}/sarcof33_photo_digitized.nc")

    rows = []
    for si, season in enumerate(SEASONS.values()):
        c = classes[si]
        for iso, m in country.items():
            mm = m & (c > 0)
            n = int(mm.sum())
            if n == 0:
                continue
            cc = c[mm]
            fr = {f"frac_{name}": float((cc == code).mean()) for code, name in CLASS_NAMES.items()}
            rows.append({
                "iso3": iso, "season": season, "n_cells": n,
                **fr,
                "dryness_score": float(sum(DRYNESS[k] * (cc == k).mean() for k in DRYNESS)),
                "frac_confident": float(confs[si][mm].mean()),
            })
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "sarcof33_country_stats.parquet", index=False)
    logger.info("\n" + df.pivot(index="iso3", columns="season", values="dryness_score").round(0).to_string())


if __name__ == "__main__":
    main()
