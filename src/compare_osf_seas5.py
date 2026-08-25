"""Compare the digitized SADC CSC MME forecasts against raw SEAS5.

For every digitized (country, issued, target season) MME slice, builds the
matching raw-SEAS5 country forecast from the team DB (public.seas5 adm0
monthly ensemble means, 1981->present) and asks: where does that SEAS5
forecast sit within its own 1993-2022 same-issue-month/same-season
climatology? That gives a SEAS5 tercile category + percentile per slice,
comparable against the official regional product's dominant tercile.

Caveat by construction: SEAS5 side is the tercile of the ENSEMBLE MEAN vs
its own climatology (the team's usual framing), not tercile probabilities —
so agreement is expected to be well below 100% even if the CSC's calibration
added nothing. The interesting question is systematic BIAS: does the
official product lean wetter or drier than raw SEAS5 for the same periods?

Output: data/processed/osf-digitized/osf_vs_seas5.parquet (one row per
country x issue x season x masked-variant, both products' categories) +
printed headline stats.
"""

import json
import logging
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
NC_DIR = ROOT / "data" / "processed" / "osf-digitized"

ISO3S = ["AGO", "BWA", "COD", "LSO", "MDG", "MOZ", "MWI", "NAM", "SWZ", "TZA", "ZAF", "ZMB", "ZWE"]
CLIM_YEARS = (1993, 2022)  # ~the CSC's own hindcast era, 30 years


def seas5_seasonal() -> pd.DataFrame:
    """(iso3, issued_date, lead 0-4) -> 3-month-mean forecast value."""
    engine = stratus.get_engine(stage="prod")
    q = f"""
        SELECT iso3, issued_date, leadtime, mean
        FROM public.seas5
        WHERE adm_level = 0 AND iso3 IN ({",".join(f"'{i}'" for i in ISO3S)})
    """
    df = pd.read_sql(q, engine, parse_dates=["issued_date"])
    wide = df.pivot_table(index=["iso3", "issued_date"], columns="leadtime", values="mean")
    rows = []
    for lead in range(5):
        val = wide[[lead, lead + 1, lead + 2]].mean(axis=1)
        sub = val.rename("seas5_value").reset_index()
        sub["lead"] = lead
        rows.append(sub)
    out = pd.concat(rows, ignore_index=True).dropna(subset=["seas5_value"])
    out["issue_month"] = out.issued_date.dt.month
    return out


def add_climatology_rank(s5: pd.DataFrame) -> pd.DataFrame:
    """Percentile + tercile of each forecast within its own (iso3, issue
    month, lead) climatology over CLIM_YEARS."""
    y0, y1 = CLIM_YEARS
    clim = s5[(s5.issued_date.dt.year >= y0) & (s5.issued_date.dt.year <= y1)]
    groups = clim.groupby(["iso3", "issue_month", "lead"])["seas5_value"]
    ref = {k: np.sort(v.values) for k, v in groups}

    def rank(row):
        r = ref.get((row.iso3, row.issue_month, row.lead))
        if r is None or len(r) < 20:
            return pd.Series({"seas5_pct": np.nan, "seas5_cat": None})
        below = (r < row.seas5_value).sum()
        equal = (r == row.seas5_value).sum()
        pct = 100 * (below + 0.5 * equal) / len(r)
        q33, q67 = np.quantile(r, [1 / 3, 2 / 3])
        cat = "below" if row.seas5_value < q33 else "above" if row.seas5_value > q67 else "normal"
        return pd.Series({"seas5_pct": pct, "seas5_cat": cat})

    return pd.concat([s5, s5.apply(rank, axis=1)], axis=1)


def era5_seasonal() -> pd.DataFrame:
    """(iso3, season start date) -> observed 3-month-mean precip (ERA5 adm0)."""
    engine = stratus.get_engine(stage="prod")
    q = f"""
        SELECT iso3, valid_date, mean
        FROM public.era5
        WHERE adm_level = 0 AND iso3 IN ({",".join(f"'{i}'" for i in ISO3S)})
    """
    df = pd.read_sql(q, engine, parse_dates=["valid_date"])
    df = df.set_index(["iso3", "valid_date"])["mean"].sort_index()
    rows = []
    for iso in ISO3S:
        s = df.loc[iso]
        val = (s + s.shift(-1) + s.shift(-2)) / 3  # mean of months m, m+1, m+2
        rows.append(pd.DataFrame({"iso3": iso, "start_date": val.index, "obs_value": val.values}))
    return pd.concat(rows, ignore_index=True).dropna()


def seas5_skill(s5: pd.DataFrame) -> pd.DataFrame:
    """Spearman rank correlation of SEAS5 seasonal forecasts vs ERA5 observed
    seasonal precip, per (iso3, issue month, lead), across all years with both.
    The team's usual 'can you trust SEAS5 here for this season/lead' number."""
    obs = era5_seasonal()
    s5 = s5.copy()
    s5["start_date"] = s5.apply(
        lambda r: r.issued_date + pd.DateOffset(months=int(r.lead)), axis=1
    )
    m = s5.merge(obs, on=["iso3", "start_date"], how="inner")
    out = []
    for (iso, mon, lead), g in m.groupby(["iso3", "issue_month", "lead"]):
        if len(g) < 20:
            continue
        rho = g.seas5_value.rank().corr(g.obs_value.rank())
        out.append({"iso3": iso, "issue_month": mon, "lead": lead, "seas5_skill": round(float(rho), 2)})
    return pd.DataFrame(out)


def write_site_json(merged: pd.DataFrame) -> None:
    """Per-slice SEAS5 reference for the site's country panel: percentile of
    the same-period SEAS5 country forecast vs 1993-2022 climatology, raw
    value (mm/day), and the country/issue-month/lead skill."""
    out: dict = {}
    sub = merged[~merged.skill_masked].dropna(subset=["seas5_pct"])
    for _, r in sub.iterrows():
        skey = f"{r.issued:%Y-%m}_{r.season}"
        out.setdefault(skey, {})[r.iso3] = [
            int(round(r.seas5_pct)),
            round(float(r.seas5_value), 2),
            None if pd.isna(r.seas5_skill) else float(r.seas5_skill),
        ]
    dest = ROOT / "docs" / "data" / "seas5_ref.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    logger.info(f"site json -> {dest} ({dest.stat().st_size // 1024} KB)")


SITE_PRODUCTS = {  # site product key -> (system column value, skill_masked)
    "sadc-mme": ("MME01", True),
    "sadc-mme-full": ("MME01", False),
    "seas51": ("SEAS51_SST-PCR", True),
    "cfsv2": ("CFSv2_SST-PCR", True),
    "geoss2s": ("GEOSS2S_SST-PCR", True),
    "ccsm4": ("CCSM4_SST-PCR", True),
}


def write_timeseries_json(osf_all: pd.DataFrame, s5: pd.DataFrame) -> None:
    """History JSON for the site's Time-series tab, on a shared 0-100
    "wet-lean" scale (50 = neutral): SEAS5 = percentile of the seasonal
    forecast vs its 1993-2022 same-issue-month climatology (from 1993 on);
    OSF = the bounded country dryness score mapped linearly
    (wetness = 50 - dryness * 50/70). Keys: "<iso3>|<season>|<issue MM>"."""
    seas5: dict = {}
    sub = s5[(s5.issued_date.dt.year >= 1993) & s5.seas5_pct.notna()].copy()
    sub["season"] = sub.apply(
        lambda r: SEASON_BY_START[(r.issue_month - 1 + r.lead) % 12 + 1], axis=1
    )
    for _, r in sub.iterrows():
        key = f"{r.iso3}|{r.season}|{r.issue_month:02d}"
        seas5.setdefault(key, {})[str(r.issued_date.year)] = int(round(r.seas5_pct))

    osf: dict = {}
    for prod, (system, masked) in SITE_PRODUCTS.items():
        d = osf_all[(osf_all.system == system) & (osf_all.skill_masked == masked)]
        for _, r in d.iterrows():
            key = f"{r.iso3}|{r.season}|{r.issued.month:02d}"
            wet = max(0.0, min(100.0, 50 - float(r.dryness_score) * 50 / 70))
            osf.setdefault(prod, {}).setdefault(key, {})[str(r.issued.year)] = round(wet, 1)

    dest = ROOT / "docs" / "data" / "timeseries.json"
    dest.write_text(json.dumps({"seas5": seas5, "osf": osf}, separators=(",", ":")))
    logger.info(f"site json -> {dest} ({dest.stat().st_size // 1024} KB)")


SEASONS_ORDER = ["MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ", "DJF", "JFM", "FMA", "MAM", "AMJ"]
SEASON_BY_START = {(i + 4) % 12 + 1: s for i, s in enumerate(SEASONS_ORDER)}


def osf_category(row) -> str | None:
    fr = {"below": row.frac_below, "normal": row.frac_normal, "above": row.frac_above}
    best = max(fr, key=fr.get)
    return best if fr[best] > 0 else None


def main() -> None:
    osf_all = pd.read_parquet(NC_DIR / "osf_country_stats.parquet")
    osf = osf_all[osf_all.system == "MME01"].copy()
    osf["osf_cat"] = osf.apply(osf_category, axis=1)

    s5 = add_climatology_rank(seas5_seasonal())
    skill = seas5_skill(s5)
    s5 = s5.merge(skill, on=["iso3", "issue_month", "lead"], how="left")
    merged = osf.merge(
        s5.rename(columns={"issued_date": "issued"}),
        on=["iso3", "issued", "lead"],
        how="left",
        validate="many_to_one",
    )
    merged.to_parquet(NC_DIR / "osf_vs_seas5.parquet", index=False)
    write_site_json(merged)
    write_timeseries_json(osf_all, s5)
    logger.info(f"{len(merged)} rows -> {NC_DIR}/osf_vs_seas5.parquet")

    for masked in (False, True):
        sub = merged[(merged.skill_masked == masked) & merged.osf_cat.notna() & merged.seas5_cat.notna()]
        both = sub[sub.osf_cat != "none"]
        logger.info(f"\n=== MME01 {'skill-masked' if masked else 'unmasked'} ({len(both)} slices) ===")
        ct = pd.crosstab(both.osf_cat, both.seas5_cat, margins=True)
        logger.info("\ncontingency (rows=OSF dominant, cols=SEAS5 mean tercile):\n" + ct.to_string())
        agree = (both.osf_cat == both.seas5_cat).mean()
        logger.info(f"category agreement: {agree:.1%}")
        logger.info(
            "marginals — OSF: "
            + ", ".join(f"{k} {v:.1%}" for k, v in both.osf_cat.value_counts(normalize=True).items())
            + " | SEAS5: "
            + ", ".join(f"{k} {v:.1%}" for k, v in both.seas5_cat.value_counts(normalize=True).items())
        )
        rho = both[["dryness_score", "seas5_pct"]].corr(method="spearman").iloc[0, 1]
        logger.info(f"spearman(dryness_score, SEAS5 wet percentile): {rho:.2f} (expect negative)")
        for cat in ("below", "above"):
            m = both.loc[both.osf_cat == cat, "seas5_pct"].mean()
            logger.info(f"mean SEAS5 wet percentile when OSF says {cat}: {m:.0f}")


if __name__ == "__main__":
    main()
