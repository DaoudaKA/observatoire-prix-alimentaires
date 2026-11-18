"""Configuration centrale du pipeline Observatoire des prix alimentaires."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.environ.get("RAW_DIR", ROOT / "data" / "raw"))
WAREHOUSE = Path(os.environ.get("WAREHOUSE", ROOT / "data" / "warehouse.duckdb"))
WEB_DATA_DIR = Path(os.environ.get("WEB_DATA_DIR", ROOT / "web" / "data"))

# Pays suivis : code ISO3 -> (slug HDX, nom français)
COUNTRIES = {
    "SEN": ("senegal", "Sénégal"),
    "MLI": ("mali", "Mali"),
    "MRT": ("mauritania", "Mauritanie"),
    "GMB": ("gambia", "Gambie"),
    "GIN": ("guinea", "Guinée"),
    "GNB": ("guinea-bissau", "Guinée-Bissau"),
    "BFA": ("burkina-faso", "Burkina Faso"),
    "CIV": ("cote-d-ivoire", "Côte d'Ivoire"),
    "NER": ("niger", "Niger"),
}

HDX_API = "https://data.humdata.org/api/3/action/package_show?id=wfp-food-prices-for-{slug}"
