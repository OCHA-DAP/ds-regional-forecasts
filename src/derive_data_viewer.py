"""Pack the Zenodo digitized-forecast NetCDFs into browser-readable data tiles.

Each (product, tercile, year) slice becomes a grayscale PNG where
pixel = round(probability * 200) and 255 = nodata. The browser reads the
values back off a canvas, so one small asset serves rendering, hover values
and the client-side percentile-vs-history computation. A manifest.json
carries grid geometry, years and attribution; a clipped/simplified country
outline (from the ACMAD African_States layer) is emitted for the overlay.

Inputs (re-download from blob raw/ if data/raw was cleaned):
  data/raw/zenodo/Consensual_Forecasts_2016_2024.nc
  data/raw/zenodo/Objective_Forecasts_2017_2024.nc
  data/tmp/African_States.geojson  (blob raw/acmad/CDD/multihazard_shapefiles/
    seasonal/202210/geojson/ — kept OUT of data/raw so upload_blob doesn't
    mirror it to a stray blob path)
Outputs: docs/data/  (gitignored; mirrored to blob site-assets by upload_blob)
"""

import json
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image

REPO = Path(__file__).parents[1]
RAW = REPO / "data" / "raw"
OUT = REPO / "docs" / "data"

SCALE = 200  # pixel = prob * SCALE; 255 = nodata
NODATA = 255

PRODUCTS = {
    "consensus": {
        "file": RAW / "zenodo" / "Consensual_Forecasts_2016_2024.nc",
        "var": "forecast",
        "label": "PRESASS consensus (digitized)",
        "note": (
            "JJAS rainfall tercile probabilities digitized from the PRESASS "
            "consensus maps. Values are the map classes (15–50%); coverage "
            "follows each year's drawn forecast zones."
        ),
    },
    "objective": {
        "file": RAW / "zenodo" / "Objective_Forecasts_2017_2024.nc",
        "var": "__xarray_dataarray_variable__",
        "label": "Objective forecast (WASS2S)",
        "note": (
            "JJAS rainfall tercile probabilities from the objective "
            "(model-based) system — continuous values over the full domain."
        ),
    },
}

ATTRIBUTION = (
    "Houngnibo et al., AGRHYMET/WAS-NextGen, doi:10.5281/zenodo.18936657 (CC-BY 4.0)"
)

# SADC OSF digitized stacks (src/digitize_osf.py). Rainfall only for the viewer.
OSF_PRODUCTS = {
    "sadc-mme": {
        "file": REPO / "data" / "processed" / "osf-digitized" / "osf_digitized_MME01.nc",
        "label": "SADC CSC MME (skill-masked)",
        "note": (
            "Rainfall tercile forecasts digitized from the SADC CSC objective "
            "multi-model ensemble maps (skill-masked product). Only the dominant "
            "tercile's probability class survives digitization — the other two "
            "terciles show 0 and white areas mean weak signal, low skill, or no "
            "data. Slices are issue month + target season; the percentile view "
            "compares only same-target-season issues."
        ),
    },
    "sadc-mme-full": {
        "file": REPO / "data" / "processed" / "osf-digitized" / "osf_digitized_MME01_unmasked.nc",
        "label": "SADC CSC MME (unmasked)",
        "note": (
            "As the skill-masked product, but without the CSC's Generalized-ROC "
            "skill mask — fuller coverage, including low-skill areas."
        ),
    },
}
OSF_ATTRIBUTION = (
    "SADC Climate Services Centre objective seasonal forecast maps "
    "(csc.sadc.int), digitized by OCHA CHD (ds-regional-forecasts)"
)


def pack_product(key: str, spec: dict) -> dict:
    da = xr.open_dataset(spec["file"])[spec["var"]]
    x, y = da["X"].values, da["Y"].values
    years = (da["T"].values.astype("datetime64[Y]").astype(int) + 1970).tolist()
    terciles = [str(p) for p in da["probability"].values]  # PB, PN, PA

    pdir = OUT / key
    pdir.mkdir(parents=True, exist_ok=True)
    for ti, terc in enumerate(terciles):
        for yi, year in enumerate(years):
            v = da.isel(probability=ti, T=yi).values
            px = np.full(v.shape, NODATA, dtype=np.uint8)
            ok = np.isfinite(v)
            px[ok] = np.clip(np.round(v[ok] * SCALE), 0, SCALE).astype(np.uint8)
            # rows top->bottom must run north->south; Y is ascending
            Image.fromarray(px[::-1], mode="L").save(
                pdir / f"{terc}_{year}.png", optimize=True
            )

    half_dx, half_dy = abs(x[1] - x[0]) / 2, abs(y[1] - y[0]) / 2
    return {
        "label": spec["label"],
        "note": spec["note"],
        "years": years,
        "terciles": terciles,
        "width": len(x),
        "height": len(y),
        # outer edges of the grid (pixel centers padded by half a cell)
        "bbox": [
            round(float(x.min() - half_dx), 3),
            round(float(y.min() - half_dy), 3),
            round(float(x.max() + half_dx), 3),
            round(float(y.max() + half_dy), 3),
        ],
        "season": "JJAS",
    }


def sadc_land_mask(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """True where a cell center falls inside a SADC country polygon."""
    import json as _json

    from shapely import contains_xy
    from shapely.geometry import shape
    from shapely.ops import unary_union

    gj = _json.loads((REPO / "data" / "tmp" / "sadc_continental.geojson").read_text())
    union = unary_union([shape(f["geometry"]) for f in gj["features"]]).buffer(0.05)
    xx, yy = np.meshgrid(lons, lats)
    return contains_xy(union, xx.ravel(), yy.ravel()).reshape(xx.shape)


def pack_osf(key: str, spec: dict) -> dict:
    """OSF digitized stacks -> tiles. Dominant tercile's class only: the
    dominant channel carries prob_lb, the other two carry 0; no-signal land
    is 0 in all channels; sea / unclassifiable is nodata."""
    ds = xr.open_dataset(spec["file"]).sel(variable="PRCP")
    lats, lons = ds["lat"].values, ds["lon"].values
    land = sadc_land_mask(lats, lons)

    slices, labels, groups = [], [], []
    pdir = OUT / key
    pdir.mkdir(parents=True, exist_ok=True)
    for ii, issued in enumerate(ds["issued"].values):
        ym = str(issued)[:7]
        for li in ds["lead"].values:
            sel = ds.isel(issued=ii).sel(lead=li)
            if not bool(sel["digitized"]):
                continue
            season = str(sel["season"].values)
            skey = f"{ym}_{season}"
            slices.append(skey)
            labels.append(f"{ym} {season}")
            groups.append(season)
            terc = sel["tercile"].values
            plb = sel["prob_lb"].values
            for ti, code in enumerate((1, 2, 3)):  # PB, PN, PA
                px = np.zeros(terc.shape, dtype=np.uint8)
                px[terc == code] = (plb[terc == code].astype(np.uint16) * 2).astype(np.uint8)
                px[(terc == -1) | ~land] = NODATA
                Image.fromarray(px, mode="L").save(
                    pdir / f"{['PB', 'PN', 'PA'][ti]}_{skey}.png", optimize=True
                )

    res = abs(lons[1] - lons[0])
    return {
        "label": spec["label"],
        "note": spec["note"],
        "attribution": OSF_ATTRIBUTION,
        "years": slices,
        "labels": labels,
        "groups": groups,
        "terciles": ["PB", "PN", "PA"],
        "width": len(lons),
        "height": len(lats),
        "bbox": [
            round(float(lons.min() - res / 2), 3),
            round(float(lats.min() - res / 2), 3),
            round(float(lons.max() + res / 2), 3),
            round(float(lats.max() + res / 2), 3),
        ],
        "season": "per slice",
    }


def make_outline(bbox: list[float]) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.read_file(REPO / "data" / "tmp" / "African_States.geojson")
    gdf.geometry = gdf.geometry.make_valid()
    pad = 1.0
    clipped = gpd.clip(gdf, box(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))
    simplified = clipped.geometry.simplify(0.02).boundary
    simplified[~simplified.is_empty].to_frame("geometry").to_file(
        OUT / "outline.geojson", driver="GeoJSON"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "scale": SCALE,
        "nodata": NODATA,
        "attribution": ATTRIBUTION,
        "products": {
            **{k: pack_product(k, spec) for k, spec in PRODUCTS.items()},
            **{k: pack_osf(k, spec) for k, spec in OSF_PRODUCTS.items()},
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))

    bboxes = [p["bbox"] for p in manifest["products"].values()]
    union = [
        min(b[0] for b in bboxes), min(b[1] for b in bboxes),
        max(b[2] for b in bboxes), max(b[3] for b in bboxes),
    ]
    make_outline(union)

    n_tiles = sum(1 for _ in OUT.rglob("*.png"))
    kb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) // 1024
    print(f"wrote {n_tiles} tiles + manifest + outline to {OUT} ({kb} KB total)")


if __name__ == "__main__":
    main()
