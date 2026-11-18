"""Agent IA de l'Observatoire (fonction serverless Vercel, runtime Python).

Boucle d'agent Claude avec deux outils :
  * run_sql    : exécute une requête SELECT en lecture seule sur observatoire.duckdb
  * show_chart : demande au front d'afficher un graphique à partir d'un résultat
La clé API reste côté serveur (variable d'environnement ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import duckdb

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
DB_PATH = Path(os.environ.get(
    "AGENT_DB", Path(__file__).resolve().parent.parent / "data" / "observatoire.duckdb"))
MAX_STEPS = 8
MAX_ROWS = 200
SQL_TIMEOUT_S = 10
RATE_LIMIT = (20, 600)  # 20 questions / 10 min / IP (au mieux, mémoire de l'instance)

_con = None
_schema_prompt = None
_hits: dict[str, deque] = defaultdict(deque)

FORBIDDEN = re.compile(
    r"\b(attach|detach|copy|export|import|install|load|pragma|create|insert|update|delete|drop|alter|"
    r"set|reset|call|checkpoint|vacuum|use|read_csv\w*|read_parquet|read_json\w*|glob|read_text|read_blob)\b",
    re.I,
)

NOTES = """
Notes métier :
- Source : prix WFP (Programme alimentaire mondial) publiés sur HDX, relevés mensuels sur les marchés.
- Les prix sont ramenés à l'unité de base indiquée dans `unit` (KG, L, ...). `currency` = monnaie locale
  (XOF = franc CFA pour Sénégal, Mali, Burkina, Côte d'Ivoire, Niger, Guinée-Bissau ; MRU Mauritanie ;
  GMD Gambie ; GNF Guinée). Pour comparer des pays, utiliser `usd_price` ou `avg_usd_price_12m`.
- `price_type` : 'Retail' (détail, à privilégier) ou 'Wholesale' (gros).
- Noms de produits : utiliser `commodity_fr` (français, ex. 'Riz (importé)', 'Oignons (local)', 'Mil')
  avec ILIKE pour être tolérant (ex. commodity_fr ILIKE '%riz%').
- Noms de marchés et régions : orthographe WFP sans accents (ex. 'Thies', 'Dakar', 'Kaolack', 'Saint-Louis').
  Toujours chercher avec ILIKE '%...%'. À Dakar, les marchés ont leur propre nom (ex. Castors, Tilene) : filtrer par region.
- prix_national_mensuel : médiane des marchés d'un pays ; mom_pct / yoy_pct = variation mensuelle / annuelle en %.
- alertes_prix : alert_level ∈ Normal, Stress, Alerte, Crise (méthode inspirée de l'ALPS du WFP : écart du prix
  à sa tendance saisonnière, standardisé). deviation_pct = écart au prix attendu en %.
- inflation_alimentaire : médiane des variations annuelles des produits suivis (approximation, pas l'IPC officiel).
- previsions_prix : prévisions Holt-Winters à 3 mois, intervalle à 80 %, backtest_mape_pct = erreur moyenne sur 6 mois.
- dim_date.is_lean_season = période de soudure (juillet-octobre).
"""


def _connect():
    global _con
    if _con is None:
        _con = duckdb.connect(str(DB_PATH), read_only=True,
                              config={"enable_external_access": False, "lock_configuration": True})
    return _con


def schema_prompt() -> str:
    global _schema_prompt
    if _schema_prompt:
        return _schema_prompt
    con = _connect()
    parts = ["Tables disponibles (DuckDB) :"]
    for (t,) in con.execute("select table_name from information_schema.tables order by 1").fetchall():
        cols = con.execute(
            "select column_name, data_type from information_schema.columns where table_name = ? order by ordinal_position",
            [t]).fetchall()
        parts.append(f"- {t}(" + ", ".join(f"{c} {d}" for c, d in cols) + ")")
    countries = con.execute("select country_iso3 || '=' || country_name || ' (' || last_month || ')' from dim_country").fetchall()
    parts.append("Pays (dernier mois disponible) : " + ", ".join(r[0] for r in countries))
    prods = con.execute("""select distinct commodity_fr from dim_commodity order by 1""").fetchall()
    parts.append("Produits : " + ", ".join(r[0] for r in prods[:150]))
    cov = con.execute("""
        with last as (select country_iso3, max(month_date) m from prix_national_mensuel group by 1)
        select n.country_iso3, string_agg(n.commodity_fr || ' ' || strftime(min_d, '%Y'), ', ' order by min_d, n.commodity_fr)
        from (select country_iso3, commodity_fr, min(month_date) min_d, max(month_date) max_d
              from prix_national_mensuel where price_type = 'Retail' group by 1, 2) n
        join last l using (country_iso3)
        where n.max_d >= l.m - interval 6 month
        group by 1 order by 1""").fetchall()
    parts.append("Produits suivis actuellement par pays (année de début de la série) :")
    parts.extend(f"- {iso} : {txt}" for iso, txt in cov)
    regions = con.execute("select distinct region from dim_market where country_iso3='SEN' and region is not null order by 1").fetchall()
    parts.append("Régions du Sénégal : " + ", ".join(r[0] for r in regions))
    _schema_prompt = "\n".join(parts) + "\n" + NOTES
    return _schema_prompt


SYSTEM_TEMPLATE = """Tu es l'analyste data de l'« Observatoire des prix alimentaires — Sénégal & Afrique de l'Ouest ».
Tu réponds en français (ou dans la langue de la question), de façon claire et chiffrée, pour un public
large : ménages, commerçants, producteurs, journalistes, décideurs.

Méthode :
1. Interroge TOUJOURS les données avec l'outil run_sql avant de donner un chiffre. N'invente jamais de valeur.
2. Commence par vérifier les libellés exacts (produit, marché, région) si besoin, avec ILIKE.
3. Quand une évolution dans le temps ou une comparaison est utile, appelle show_chart.
4. Cohérence : ne mélange JAMAIS deux produits différents dans une même série, un même tableau ou une même
   colonne (ex. « Oignons secs » et « Oignons (importés) » sont deux séries distinctes). Si le produit ou la
   période demandés ne sont pas disponibles, dis-le d'abord clairement, puis propose le produit ou la période
   disponible la plus proche, nommés explicitement. Vérifie la couverture (liste ci-dessous) avant de répondre.
5. « Au Sénégal » (sans marché précis) = prix national (médiane des marchés) ; un marché ou une région précis =
   prix des marchés concernés. Indique toujours de quel niveau il s'agit.
6. Si la question sort du périmètre (prix alimentaires des pays suivis), dis-le poliment.

Format de la réponse finale (Markdown, ton d'analyste senior, sobre, sans emoji, sans formule de politesse) :
- Première ligne : la conclusion principale en une phrase, en **gras**, avec le chiffre clé, l'unité et le mois
  (ex. « **Le riz importé coûte 325 FCFA/kg au Sénégal en octobre 2026, en baisse de 7 % sur un an.** »).
- Ensuite, selon le besoin :
  * un tableau Markdown dès qu'il y a au moins 3 valeurs à comparer (marchés, pays, mois). 6 colonnes et
    12 lignes au plus ; en-têtes courts ; unité dans l'en-tête (ex. « Prix (FCFA/kg) ») ; chiffres arrondis
    (FCFA sans décimale, % à une décimale, format français : 1 250 ; 3,5 %) ;
  * 2 à 4 puces d'analyse : ce qu'il faut retenir, pas une répétition du tableau.
- Dernière ligne, en italique, seulement si utile : la limite principale (ex. « *Prévision indicative : erreur
  moyenne du modèle de 6 % sur les 6 derniers mois.* »).
- 180 mots au plus hors tableau. Pas de titre de niveau 1, pas de SQL, pas de noms de tables ou de colonnes,
  pas de phrase du type « d'après les données » ou « j'ai interrogé la base ».

{schema}"""

TOOLS = [
    {
        "name": "run_sql",
        "description": "Exécute UNE requête SQL DuckDB en lecture seule (SELECT ou WITH) et renvoie au plus 200 lignes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Requête SELECT/WITH DuckDB."},
                "purpose": {"type": "string", "description": "Objectif de la requête, en une phrase."},
            },
            "required": ["query", "purpose"],
        },
    },
    {
        "name": "show_chart",
        "description": ("Affiche un graphique à l'utilisateur à partir du résultat d'une requête run_sql déjà exécutée. "
                        "query_index = numéro de la requête (0 = première)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query_index": {"type": "integer"},
                "type": {"type": "string", "enum": ["line", "bar"]},
                "x": {"type": "string", "description": "Colonne de l'axe X."},
                "y": {"type": "string", "description": "Colonne numérique de l'axe Y."},
                "series": {"type": "string", "description": "Colonne optionnelle qui sépare les séries."},
                "title": {"type": "string"},
            },
            "required": ["query_index", "type", "x", "y", "title"],
        },
    },
]


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float) and v != v:
        return None
    return v


def validate_sql(sql: str) -> str:
    q = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if ";" in q:
        raise ValueError("Une seule requête à la fois.")
    if not re.match(r"^(select|with)\b", q, re.I):
        raise ValueError("Seules les requêtes SELECT/WITH sont autorisées.")
    without_strings = re.sub(r"'(?:[^']|'')*'", "''", q)  # les littéraux ('Riz (importé)') ne comptent pas
    if FORBIDDEN.search(without_strings):
        raise ValueError("Mot-clé non autorisé dans la requête.")
    return q


def run_sql(sql: str) -> dict:
    q = validate_sql(sql)
    con = _connect().cursor()
    timer = threading.Timer(SQL_TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        cur = con.execute(q)
        cols = [d[0] for d in cur.description]
        rows = [[_jsonable(v) for v in r] for r in cur.fetchmany(MAX_ROWS + 1)]
    finally:
        timer.cancel()
        con.close()
    return {"columns": cols, "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


def ask(question: str, history: list[dict] | None = None, client=None) -> dict:
    """Pose une question à l'agent. `client` injectable pour les tests."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    system = [{"type": "text", "text": SYSTEM_TEMPLATE.format(schema=schema_prompt()),
               "cache_control": {"type": "ephemeral"}}]
    messages = []
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:4000]})
    messages.append({"role": "user", "content": question})

    queries, charts = [], []
    usage = {"input_tokens": 0, "output_tokens": 0}
    for _ in range(MAX_STEPS):
        resp = client.messages.create(model=MODEL, max_tokens=2000, system=system,
                                      tools=TOOLS, messages=messages)
        usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"answer": text, "queries": queries, "charts": charts, "usage": usage}

        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "run_sql":
                sql = block.input.get("query", "")
                try:
                    res = run_sql(sql)
                    queries.append({"sql": sql, "purpose": block.input.get("purpose", ""), **res})
                    payload = json.dumps({"query_index": len(queries) - 1, **res}, ensure_ascii=False)[:20000]
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": payload})
                except Exception as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Erreur SQL : {exc}", "is_error": True})
            elif block.name == "show_chart":
                spec = dict(block.input)
                i = spec.get("query_index", -1)
                if 0 <= i < len(queries) and spec.get("x") in queries[i]["columns"] and spec.get("y") in queries[i]["columns"]:
                    charts.append(spec)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": "Graphique affiché."})
                else:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": "query_index ou colonnes invalides."})
        messages.append({"role": "user", "content": results})

    return {"answer": "Je n'ai pas pu conclure l'analyse en un nombre raisonnable d'étapes. Reformulez la question.",
            "queries": queries, "charts": charts, "usage": usage}


def _rate_limited(ip: str) -> bool:
    n, window = RATE_LIMIT
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= n:
        return True
    q.append(now)
    return False


class handler(BaseHTTPRequestHandler):  # noqa: N801 (nom imposé par Vercel)
    def _send(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        ip = (self.headers.get("x-forwarded-for") or self.client_address[0]).split(",")[0].strip()
        if _rate_limited(ip):
            return self._send(429, {"error": "Trop de questions, réessayez dans quelques minutes."})
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 100_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            question = str(body.get("question", "")).strip()
            if not question or len(question) > 600:
                return self._send(400, {"error": "Question vide ou trop longue (600 caractères max)."})
            if not os.environ.get("ANTHROPIC_API_KEY"):
                return self._send(503, {"error": "Agent non configuré (ANTHROPIC_API_KEY manquante)."})
            self._send(200, ask(question, body.get("history")))
        except Exception as exc:
            self._send(500, {"error": f"Erreur de l'agent : {type(exc).__name__}"})

    def do_GET(self):  # noqa: N802 — santé
        self._send(200, {"status": "ok", "model": MODEL, "db": DB_PATH.exists()})
