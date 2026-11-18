"""Tests de l'agent sans appel réseau (client Claude simulé)."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("AGENT_DB", str(Path(os.environ.get("WEB_DATA_DIR", ROOT / "web" / "data")) / "observatoire.duckdb"))
spec = importlib.util.spec_from_file_location("agent", ROOT / "web" / "api" / "agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


@pytest.mark.parametrize("sql", [
    "DROP TABLE dim_country",
    "select 1; drop table dim_country",
    "select * from read_csv_auto('/etc/passwd')",
    "COPY dim_country TO 'x.csv'",
    "ATTACH 'x.db'",
])
def test_sql_refusee(sql):
    with pytest.raises(ValueError):
        agent.validate_sql(sql)


def test_sql_lecture():
    res = agent.run_sql("select commodity_fr from dim_commodity where commodity_fr ilike '%riz (import%'")
    assert res["rows"] and res["columns"] == ["commodity_fr"]


def test_schema_prompt_contient_tables():
    p = agent.schema_prompt()
    for t in ("prix_national_mensuel", "alertes_prix", "previsions_prix", "Sénégal"):
        assert t in p


class FakeClient:
    """Simule Claude : 1) appelle run_sql, 2) show_chart, 3) répond."""
    def __init__(self):
        self.step = 0
        self.messages = self

    def create(self, **kw):
        self.step += 1
        u = NS(input_tokens=10, output_tokens=5)
        if self.step == 1:
            return NS(stop_reason="tool_use", usage=u, content=[NS(type="tool_use", id="t1", name="run_sql", input={
                "query": "select month_date, price from prix_national_mensuel where country_iso3='SEN' "
                         "and commodity_fr ilike '%riz%' and price_type='Retail' order by month_date",
                "purpose": "Série du riz"})])
        if self.step == 2:
            return NS(stop_reason="tool_use", usage=u, content=[NS(type="tool_use", id="t2", name="show_chart", input={
                "query_index": 0, "type": "line", "x": "month_date", "y": "price", "title": "Riz"})])
        return NS(stop_reason="end_turn", usage=u, content=[NS(type="text", text="Le riz coûte X FCFA/kg.")])


def test_boucle_agent():
    out = agent.ask("Prix du riz au Sénégal ?", client=FakeClient())
    assert out["answer"].startswith("Le riz")
    assert len(out["queries"]) == 1 and out["queries"][0]["rows"]
    assert out["charts"][0]["y"] == "price"
    assert out["usage"]["input_tokens"] == 30
