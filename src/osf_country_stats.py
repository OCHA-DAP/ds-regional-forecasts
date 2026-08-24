"""Per-country stats + extremeness ranking for the digitized SADC OSF forecasts.

For every digitized (system, product, issued, target season) rainfall slice,
computes per-country area fractions by dominant tercile / probability class
plus a single signed "dryness score", then ranks each issue against all other
issues for the same country + target season — the "how extreme is the new
forecast vs past ones" view. Re-run after each grab+digitize cycle; the
newest issue's ranking is printed at the end.

Dryness score = area-weighted sum over signal cells of (+prob_lb) where
below-normal dominates and (-prob_lb) where above-normal dominates, divided
by all in-country cells (no-signal cells dilute toward 0). Range roughly
-70..+70; positive = drier-leaning outlook.

Outputs (blob processed/osf-digitized/ + local data/processed/osf-digitized/):
  osf_country_stats.parquet       one row per (file, country, issued, lead)
  osf_country_extremeness.parquet stats + within-record percentile ranks
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely import contains_xy
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
NC_DIR = ROOT / "data" / "processed" / "osf-digitized"
OUT_DIR = NC_DIR  # alongside the NetCDFs; mirrored to blob by upload_blob

ISO3 = {
    "Angola": "AGO", "Democratic Republic of the Congo": "COD", "Madagascar": "MDG",
    "Mozambique": "MOZ", "Malawi": "MWI", "South Africa": "ZAF", "Lesotho": "LSO",
    "Botswana": "BWA", "United Republic of Tanzania": "TZA", "Namibia": "NAM",
    "Swaziland": "SWZ", "Zambia": "ZMB", "Zimbabwe": "ZWE",
}


def country_masks(lats: np.ndarray, lons: np.ndarray) -> dict[str, np.ndarray]:
    gj = json.loads((ROOT / "data" / "tmp" / "sadc_continental.geojson").read_text())
    xx, yy = np.meshgrid(lons, lats)
    masks = {}
    for f in gj["features"]:
        iso = ISO3[f["properties"]["NAME"]]
        geom = shape(f["geometry"]).buffer(0.02)
        masks[iso] = contains_xy(geom, xx.ravel(), yy.ravel()).reshape(xx.shape)
    return masks


def slice_stats(terc: np.ndarray, plb: np.ndarray, mask: np.ndarray) -> dict | None:
    m = mask & (terc >= 0)  # in-country, classifiable
    n = int(m.sum())
    if n == 0:
        return None
    t, p = terc[m], plb[m].astype(float)
    below, above, normal = t == 1, t == 3, t == 2
    return {
        "n_cells": n,
        "frac_below": below.mean(),
        "frac_normal": normal.mean(),
        "frac_above": above.mean(),
        "frac_below_ge50": (below & (p >= 50)).mean(),
        "frac_above_ge50": (above & (p >= 50)).mean(),
        "dryness_score": (np.where(below, p, 0) - np.where(above, p, 0)).mean(),
    }


def run() -> pd.DataFrame:
    rows = []
    masks = None
    for nc in sorted(NC_DIR.glob("osf_digitized_*.nc")):
        ds = xr.open_dataset(nc)
        if "PRCP" not in ds["variable"].values:
            continue
        ds = ds.sel(variable="PRCP")
        if masks is None:
            masks = country_masks(ds["lat"].values, ds["lon"].values)
        system = nc.stem.replace("osf_digitized_", "").replace("_unmasked", "")
        skill_masked = not nc.stem.endswith("_unmasked")
        for ii, issued in enumerate(ds["issued"].values):
            for li in ds["lead"].values:
                sel = ds.isel(issued=ii).sel(lead=li)
                if not bool(sel["digitized"]):
                    continue
                terc, plb = sel["tercile"].values, sel["prob_lb"].values
                for iso, mask in masks.items():
                    st = slice_stats(terc, plb, mask)
                    if st is None:
                        continue
                    rows.append(
                        {
                            "system": system,
                            "skill_masked": skill_masked,
                            "iso3": iso,
                            "issued": pd.Timestamp(issued),
                            "lead": int(li),
                            "season": str(sel["season"].values),
                            **st,
                        }
                    )
    df = pd.DataFrame(rows)

    # extremeness: within (system, masked, country, season), midrank percentile
    # across ALL issues of that target season (mixed leads — noted in docs)
    def midrank_pct(s: pd.Series) -> pd.Series:
        return 100 * (s.rank(method="average") - 0.5) / s.notna().sum()

    grp = df.groupby(["system", "skill_masked", "iso3", "season"])
    df["dryness_pct_rank"] = grp["dryness_score"].transform(midrank_pct)
    df["frac_below_pct_rank"] = grp["frac_below"].transform(midrank_pct)
    df["n_record"] = grp["dryness_score"].transform("count")
    return df


if __name__ == "__main__":
    df = run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / "osf_country_stats.parquet", index=False)
    # the ranked view is the same table sorted for humans
    df.sort_values(["system", "skill_masked", "iso3", "season", "issued"]).to_parquet(
        OUT_DIR / "osf_country_extremeness.parquet", index=False
    )
    logger.info(f"{len(df)} rows -> {OUT_DIR}/osf_country_stats.parquet")

    latest = df[df.system == "MME01"].sort_values("issued").issued.max()
    view = df[(df.system == "MME01") & ~df.skill_masked & (df.issued == latest)]
    logger.info(f"\nLatest MME01 issue {latest:%Y-%m} (unmasked), dryness rank vs same-season record:")
    cols = ["iso3", "season", "lead", "dryness_score", "dryness_pct_rank", "n_record"]
    logger.info("\n" + view[cols].sort_values(["season", "iso3"]).to_string(index=False))
