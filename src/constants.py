PROJECT_PREFIX = "ds-regional-forecasts"

# ACMAD THREDDS: TLS cert on 443 is expired; the port-8080 plain-HTTP endpoint
# serves the same tree.
THREDDS_BASE = "http://sgbd.acmad.org:8080/thredds"

# THREDDS subtrees holding the core seasonal products. Filenames inside are
# hand-authored and inconsistent — always enumerate via catalog.xml, never
# construct file URLs.
ACMAD_SEASONAL_TREES = [
    # Continental LRF, shapefile-centric tree (2018, 2019, 2025, 2026)
    "ACMAD/CDD/longrangeforecastingservice",
    # Continental LRF, PDF-centric CLIMSA tree (2021-2023)
    "ACMAD/PROJECTS/CLIMSA/CDD/ACTIVITIES/SERVICES/Long_Range_Forecast",
    # RCOF outputs hosted by ACMAD (PRESASS, PRESAGG, PRESAC, MEDCOF, SWIOCOF...)
    "ACMAD/PROJECTS/CLIMSA/CDD/ACTIVITIES/SERVICES/Climate_outlook_forum",
    # LRF policy briefs 2022-2023
    "ACMAD/CDD/LRF_generation/Brief/Breif_prod",
    # Seasonal forecast polygons as shapefiles, 2022 only
    "ACMAD/CDD/multihazard_shapefiles/seasonal",
]

AGRHYMET_WP_API = "https://agrhymet.cilss.int/wp-json/wp/v2"

ZENODO_RECORD = "18936657"  # WAS-NextGen digitized consensus forecasts (CC-BY 4.0)
# The 1.3 GB obs/forcing zip is excluded; we only need the forecast NetCDFs.
ZENODO_FILES = [
    "Consensual_Forecasts_2016_2024.nc",
    "Objective_Forecasts_2017_2024.nc",
]
