"""Génère un petit jeu de données FACTICE au format HDX, uniquement pour les tests.

Ne jamais utiliser pour le dashboard publié : les vraies données viennent de HDX.
Usage : python -m tests.make_fixture tests/fixtures
"""
import random
import sys
from pathlib import Path

HXL = "#date,#adm1+name,#adm2+name,#loc+market+name,#loc+market+code,#geo+lat,#geo+lon,#item+type,#item+name,#item+code,#item+unit,#item+price+flag,#item+price+type,#currency+code,#value,#value+usd"
HEAD = "date,admin1,admin2,market,market_id,latitude,longitude,category,commodity,commodity_id,unit,priceflag,pricetype,currency,price,usdprice"

MARKETS = {
    "sen": [("Dakar", "Dakar", "Castors", 14.71, -17.45), ("Thies", "Thies", "Thies", 14.79, -16.93),
            ("Kaolack", "Kaolack", "Kaolack", 14.15, -16.07), ("Saint-Louis", "Saint-Louis", "Saint-Louis", 16.03, -16.49),
            ("Ziguinchor", "Ziguinchor", "Ziguinchor", 12.56, -16.27), ("Diourbel", "Mbacke", "Touba", 14.86, -15.88)],
    "mli": [("Bamako", "Bamako", "Bamako", 12.64, -8.0), ("Kayes", "Kayes", "Kayes", 14.45, -11.44)],
}
GOODS = [("cereals and tubers", "Rice (imported)", "KG", 380), ("cereals and tubers", "Millet", "KG", 280),
         ("vegetables and fruits", "Onions (local)", "KG", 350), ("oil and fats", "Oil (vegetable)", "L", 1100),
         ("miscellaneous food", "Sugar", "KG", 600)]


def main(out: Path) -> None:
    random.seed(42)
    out.mkdir(parents=True, exist_ok=True)
    for iso, markets in MARKETS.items():
        lines = [HEAD, HXL]
        for mi, (a1, a2, mk, lat, lon) in enumerate(markets):
            for gi, (cat, com, unit, base) in enumerate(GOODS):
                for y in range(2019, 2026):
                    for m in range(1, 13):
                        t = (y - 2019) * 12 + m
                        season = 1 + (0.25 if com.startswith("Onions") and m in (8, 9, 10, 11) else 0)
                        shock = 1.3 if (y == 2022 and m >= 4) or y == 2023 else 1
                        p = base * (1 + 0.004 * t) * season * shock * random.uniform(0.95, 1.05)
                        lines.append(f"{y}-{m:02d}-15,{a1},{a2},{mk},{mi},{lat},{lon},{cat},{com},{gi},{unit},actual,Retail,XOF,{p:.0f},{p/600:.3f}")
        (out / f"wfp_food_prices_{iso}.csv").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"))
