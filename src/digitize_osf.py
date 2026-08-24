"""Digitize the SADC CSC objective-seasonal-forecast tercile maps back into data.

The CSC publishes only rendered JPGs (the NetCDFs never leave their internal
system — see CLAUDE.md), but the rendering recipe is public in sadccsc/osf
(functions_plot.py): dominant-tercile probability classes drawn with known
matplotlib colormaps at known level breaks on a cartopy PlateCarree axes,
figsize 5x5 at dpi=300, clipped to sadc_continental.geojson. That makes the
images losslessly reversible to the plotted classes:

- grid: 0.25 deg cells, centers at .125 offsets (verified from cell-edge combs)
- georeferencing: affine fitted once by aligning the CSC's own boundary
  geojson to the drawn borders (CALIB below), then phase-refined per image
- classes: dominant tercile + probability class lower bound in {40,50,60,70}
  ({40,50,70} for the normal tercile). The 33-40 class of every ramp renders
  (near-)white and cannot be told apart from masked/no-data, so it collapses
  into code 0 = "no signal" (documented in the NetCDF attrs).

What is NOT recoverable: continuous probabilities, anything under the CSC
logo (top-right corner of the axes), and the sub-dominant tercile probs.

Outputs one NetCDF per (system, predictor) group to data/processed/, dims
(variable, issued, lead) x (lat, lon), int8 `tercile` + uint8 `prob_lb`.
"""

import logging
import re
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
RAW = ROOT / "data" / "raw" / "sadc" / "osf-seasonal"
OUT = ROOT / "data" / "processed" / "osf-digitized"

# --- calibration (1500x1500 px @ dpi 300; fitted 2026-08 against
# sadccsc/csis gis/sadc_continental.geojson, boundary-overlap score 0.74)
PX_PER_DEG = 26.45
LON_AT_X0 = 6.986
LAT_AT_Y0 = 13.339
FRAME = (74, 1200, 139, 1346)  # axes box: x0, x1, y0, y1
RES = 0.25

# canonical cell-center grid (covers the axes box)
LONS = np.arange(10.125, 52.1251, RES)
LATS = np.arange(7.875, -37.3751, -RES)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASONS = ["MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ", "DJF", "JFM", "FMA", "MAM", "AMJ"]
SEASON_START = {s: (i + 4) % 12 + 1 for i, s in enumerate(SEASONS)}

# --- palettes: ramp colors for classes [33-40, 40-50, 50-60, 60-70, 70-100]
# (normal: [33-40, 40-50, 50-70, 70-100]), sampled from the exact colormap
# calls in sadccsc/osf functions_plot.py
BROWNS = [(245, 245, 244), (246, 232, 195), (222, 193, 123), (191, 129, 45), (139, 80, 10)]  # BrBG_r .5-.9
TEALS = [(244, 245, 245), (199, 234, 229), (127, 204, 192), (53, 151, 143), (1, 101, 93)]  # BrBG .5-.9
GREYS = [(255, 255, 255), (233, 233, 233), (198, 198, 198), (149, 149, 149)]  # Greys 0-.5
RDYLBU_BLUES = [(254, 255, 192), (224, 243, 248), (170, 216, 233), (116, 173, 209), (69, 116, 179)]
RDYLBU_REDS = [(255, 254, 190), (254, 224, 144), (253, 173, 96), (244, 109, 67), (214, 47, 39)]

LB_5 = [33, 40, 50, 60, 70]
LB_4 = [33, 40, 50, 70]

# variable -> (below ramp, above ramp); per the plot code's category branches:
# PRCP = "rainfall" branch, onsetD = "onset" branch (reversed), everything
# else (CDD "number_of_days", Rx5 "max_daily_rainfall", TG) = RdYlBu branch
VAR_RAMPS = {
    "PRCP": (BROWNS, TEALS),
    "onsetD": (TEALS, BROWNS),
    "CDD": (RDYLBU_BLUES, RDYLBU_REDS),
    "Rx5": (RDYLBU_BLUES, RDYLBU_REDS),
    "TG": (RDYLBU_BLUES, RDYLBU_REDS),
}

MAX_COLOR_DIST = 60  # L1 RGB distance tolerance (JPEG noise)
SAMPLE_OFFSETS = [(0, 0), (-2, 0), (2, 0), (0, -2), (0, 2)]  # dodge 1px border lines

# the CSC logo is drawn INSIDE the axes at transAxes (0.99, 0.99) and its
# colors alias with the palettes — cells under it are unrecoverable
# (open Indian Ocean for the SADC domain, so nothing of value is lost)
LOGO_BOX = (46.6, 52.4, 2.2, 8.0)  # lon_min, lon_max, lat_min, lat_max

FNAME_RE = re.compile(
    r"^(?P<var>[A-Za-z0-9]+)_(?P<prod>prob-tercile(?:-m)?)_(?P<system>MME01|SEAS51|CFSv2|GEOSS2S|CCSM4)"
    r"(?:_(?P<pred>[A-Za-z0-9-]+))?_(?P<year>\d{4})-(?P<mon>[A-Za-z]{3})_(?P<seas>[A-Z]{3})\.jpg$"
)


def build_palette(var: str):
    below, above = VAR_RAMPS[var]
    entries = (
        [(1, lb, c) for lb, c in zip(LB_5, below)]
        + [(2, lb, c) for lb, c in zip(LB_4, GREYS)]
        + [(3, lb, c) for lb, c in zip(LB_5, above)]
    )
    return (
        np.array([c for _, _, c in entries]),
        np.array([t for t, _, _ in entries], dtype=np.int8),
        np.array([lb for _, lb, _ in entries], dtype=np.uint8),
    )


def refine_phase(im: np.ndarray) -> tuple[float, float]:
    """Sub-pixel shift so 0.25-degree cell edges land on color-transition combs."""
    x0f, x1f, y0f, y1f = FRAME
    inner = im[y0f + 5 : y1f - 5, x0f + 5 : x1f - 5]
    dxp = np.abs(np.diff(inner, axis=1)).sum(axis=2).sum(axis=0).astype(float)
    dyp = np.abs(np.diff(inner, axis=0)).sum(axis=2).sum(axis=1).astype(float)
    ks = np.arange(-1000, 1000)

    def best(profile, edge_px):
        top = (0.0, 0.0)
        for shift in np.arange(-4, 4.01, 0.1):
            pos = edge_px + shift
            pos = pos[(pos > 1) & (pos < len(profile) - 1)].astype(int)
            s = profile[pos].mean()
            if s > top[0]:
                top = (s, shift)
        return top[1]

    shx = best(dxp, (RES * ks - LON_AT_X0) * PX_PER_DEG - (x0f + 5))
    shy = best(dyp, (LAT_AT_Y0 - RES * ks) * PX_PER_DEG - (y0f + 5))
    return LON_AT_X0 - shx / PX_PER_DEG, LAT_AT_Y0 + shy / PX_PER_DEG


def _classify_at(im, ys, xs, pal, terc, plb, tercile, prob_lb, todo):
    """Vectorized: 3x3 median color at (ys,xs) for cells still marked todo."""
    jj, ii = np.nonzero(todo)
    y, x = ys[jj], xs[ii]
    patches = np.stack(
        [im[y + dy, x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=1
    )  # (n, 9, 3)
    med = np.median(patches, axis=1)  # (n, 3)
    dist = np.abs(med[:, None, :] - pal[None, :, :]).sum(axis=2)  # (n, npal)
    k = dist.argmin(axis=1)
    good = dist[np.arange(len(k)), k] <= MAX_COLOR_DIST
    weak = good & (plb[k] == 33)
    strong = good & (plb[k] != 33)
    tercile[jj[weak], ii[weak]] = 0
    tercile[jj[strong], ii[strong]] = terc[k[strong]]
    prob_lb[jj[strong], ii[strong]] = plb[k[strong]]
    todo[jj[good], ii[good]] = False


def digitize_image(path: Path, var: str) -> tuple[np.ndarray, np.ndarray]:
    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    if im.shape != (1500, 1500, 3):
        raise ValueError(f"unexpected image shape {im.shape}: {path.name}")
    lon0, lat0 = refine_phase(im)
    pal, terc, plb = build_palette(var)

    tercile = np.full((len(LATS), len(LONS)), -1, dtype=np.int8)
    prob_lb = np.zeros((len(LATS), len(LONS)), dtype=np.uint8)
    ys = ((lat0 - LATS) * PX_PER_DEG).round().astype(int)
    xs = ((LONS - lon0) * PX_PER_DEG).round().astype(int)
    todo = np.ones((len(LATS), len(LONS)), dtype=bool)
    for dy, dx in SAMPLE_OFFSETS:
        _classify_at(im, ys + dy, xs + dx, pal, terc, plb, tercile, prob_lb, todo)
        if not todo.any():
            break
    lo_lon, hi_lon, lo_lat, hi_lat = LOGO_BOX
    logo = ((LATS >= lo_lat) & (LATS <= hi_lat))[:, None] & ((LONS >= lo_lon) & (LONS <= hi_lon))[None, :]
    tercile[logo] = -1
    prob_lb[logo] = 0
    return tercile, prob_lb


def run() -> None:
    files = sorted(RAW.rglob("*.jpg"))
    logger.info(f"{len(files)} images")
    # group records by (system, predictor)
    groups: dict[tuple[str, str], list] = {}
    for f in files:
        m = FNAME_RE.match(f.name)
        if not m:
            logger.warning(f"unparsed filename: {f.name}")
            continue
        # masked (-m) and unmasked variants are different products — separate files
        groups.setdefault((m["system"], m["pred"] or "", m["prod"]), []).append((f, m))

    OUT.mkdir(parents=True, exist_ok=True)
    for (system, pred, prod), items in groups.items():
        variables = sorted({m["var"] for _, m in items})
        issues = sorted({f"{m['year']}-{MONTHS.index(m['mon']) + 1:02d}" for _, m in items})
        leads = list(range(5))
        shape = (len(variables), len(issues), len(leads), len(LATS), len(LONS))
        terc = np.full(shape, -1, dtype=np.int8)
        plb = np.zeros(shape, dtype=np.uint8)
        season = np.full((len(issues), len(leads)), "", dtype="U3")
        have = np.zeros((len(variables), len(issues), len(leads)), dtype=bool)

        for f, m in items:
            issued = f"{m['year']}-{MONTHS.index(m['mon']) + 1:02d}"
            lead = (SEASON_START[m["seas"]] - (MONTHS.index(m["mon"]) + 1)) % 12
            if lead >= len(leads):
                logger.warning(f"lead {lead} out of range: {f.name}")
                continue
            vi, ii = variables.index(m["var"]), issues.index(issued)
            t, p = digitize_image(f, m["var"])
            terc[vi, ii, lead], plb[vi, ii, lead] = t, p
            season[ii, lead] = m["seas"]
            have[vi, ii, lead] = True
            unk = (t == -1).sum()
            logger.info(f"{f.name}: signal {(t > 0).sum()}, unknown {unk}")

        ds = xr.Dataset(
            {
                "tercile": (("variable", "issued", "lead", "lat", "lon"), terc),
                "prob_lb": (("variable", "issued", "lead", "lat", "lon"), plb),
                "season": (("issued", "lead"), season),
                "digitized": (("variable", "issued", "lead"), have),
            },
            coords={
                "variable": variables,
                "issued": [np.datetime64(i, "ns") for i in issues],
                "lead": leads,
                "lat": LATS,
                "lon": LONS,
            },
            attrs={
                "title": f"SADC CSC objective seasonal forecast, digitized from published maps ({system}{' ' + pred if pred else ''}, {prod})",
                "skill_masked": str(prod.endswith("-m")),
                "source": "http://csc.sadc.int/climate-prediction (rendered JPGs); rendering recipe github.com/sadccsc/osf",
                "method": "color-class inversion; see ds-regional-forecasts src/digitize_osf.py",
                "tercile_codes": "-1 unclassifiable (border/logo overprint), 0 no signal (prob<40, masked, or no data - indistinguishable), 1 below-normal, 2 normal, 3 above-normal",
                "prob_lb_meaning": "lower bound of dominant-tercile probability class: 40 (40-50), 50 (50-60; 50-70 for normal), 60 (60-70), 70 (70-100); 0 where tercile<=0",
                "grid": "0.25 deg cell centers; CHIRPS/ERA5-based predictand grid",
                "history": "digitized 2026-08 by OCHA CHD DS",
            },
        )
        suffix = "" if prod.endswith("-m") else "_unmasked"
        name = f"osf_digitized_{system}{'_' + pred if pred else ''}{suffix}.nc"
        enc = {v: {"zlib": True, "complevel": 4} for v in ("tercile", "prob_lb")}
        ds.to_netcdf(OUT / name, encoding=enc)
        logger.info(f"wrote {OUT / name} ({len(items)} images)")


if __name__ == "__main__":
    run()
