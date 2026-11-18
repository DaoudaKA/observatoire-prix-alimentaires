/* Observatoire des prix alimentaires — dashboard */
"use strict";

const STATUS = {
  Normal: { color: "#0ca30c", icon: "●", label: "Normal" },
  Stress: { color: "#fab219", icon: "▲", label: "Stress" },
  Alerte: { color: "#ec835a", icon: "◆", label: "Alerte" },
  Crise:  { color: "#d03b3b", icon: "■", label: "Crise" },
};
const LEVEL_RANK = { Normal: 0, Stress: 1, Alerte: 2, Crise: 3 };
const CUR = { XOF: "FCFA", MRU: "MRU", GMD: "GMD", GNF: "GNF", USD: "$" };
const MAX_INFL = 4;

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const SERIES = () => [css("--series-1"), css("--series-2"), css("--series-3"), css("--series-4")];
const nf = (d = 0) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtPrice = (v, cur) => v == null ? "—" : `${nf(v >= 100 ? 0 : v >= 10 ? 1 : 2).format(v)} ${CUR[cur] || cur}`;
const fmtPct = (v) => v == null ? "—" : `${v > 0 ? "+" : ""}${nf(1).format(v)} %`;
const fmtMonth = (d) => new Date(d + "T00:00:00").toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (id) => document.getElementById(id);

const state = { country: "SEN", seriesId: null, range: 60, inflCountries: ["SEN", "MLI", "MRT"], cmp: null };
const D = {};
const charts = {};
let map, mapLayer;

async function load(name) {
  const r = await fetch(`data/${name}`);
  if (!r.ok) throw new Error(name);
  return r.json();
}

function baseChart(id) {
  if (!charts[id]) {
    charts[id] = echarts.init($(id), null, { renderer: "svg" });
    window.addEventListener("resize", () => charts[id].resize());
  }
  return charts[id];
}

function axisCommon() {
  return {
    axisLine: { lineStyle: { color: css("--axis") } },
    axisTick: { show: false },
    axisLabel: { color: css("--muted"), fontSize: 11 },
    splitLine: { lineStyle: { color: css("--grid"), width: 1 } },
  };
}
const tooltipBase = () => ({
  backgroundColor: css("--surface-1"), borderColor: css("--border"),
  textStyle: { color: css("--text-primary"), fontSize: 12 }, extraCssText: "box-shadow:0 4px 14px rgba(0,0,0,.12);border-radius:8px;",
});

/* ---------- Initialisation ---------- */
async function init() {
  const [meta, countries, national, inflation, comparison, alerts, forecast] = await Promise.all(
    ["meta.json", "countries.json", "national.json", "inflation.json", "comparison.json", "alerts.json", "forecast.json"].map(load));
  Object.assign(D, { meta, countries, national, inflation, comparison, alerts, forecast, markets: {} });
  $("fresh").textContent = `Données jusqu'à ${fmtMonth(meta.last_month)} · mises à jour le ${new Date(meta.generated_at).toLocaleDateString("fr-FR")}`;

  const sel = $("country");
  sel.innerHTML = countries.map((c) => `<option value="${c.country_iso3}">${esc(c.country_name)}</option>`).join("");
  if (!countries.some((c) => c.country_iso3 === state.country)) state.country = countries[0].country_iso3;
  sel.value = state.country;
  sel.onchange = () => { state.country = sel.value; state.seriesId = null; renderCountry(); };

  $("commodity").onchange = (e) => { state.seriesId = e.target.value; renderEvolution(); renderMarkets(); };
  document.querySelectorAll(".seg button").forEach((b) => b.onclick = () => {
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    state.range = +b.dataset.range; renderEvolution();
  });
  document.querySelectorAll("[data-table]").forEach((b) => b.onclick = () => {
    const t = $(b.dataset.table + "-table"), c = $(b.dataset.table);
    const show = t.hidden; t.hidden = !show; c.style.display = show ? "none" : "";
    b.textContent = show ? "Graphique" : "Tableau";
    if (!show) charts[b.dataset.table]?.resize();
  });

  state.inflCountries = state.inflCountries.filter((c) => countries.some((x) => x.country_iso3 === c));
  setupAgent();
  renderCountry();
  renderInflation();
}

function countrySeries() {
  return D.national.filter((s) => s.country === state.country && s.d.length >= 6)
    .sort((a, b) => a.commodity.localeCompare(b.commodity, "fr"));
}

async function renderCountry() {
  const list = countrySeries();
  const sel = $("commodity");
  sel.innerHTML = list.map((s) => `<option value="${esc(s.id)}">${esc(s.commodity)} — ${esc(s.unit)}</option>`).join("");
  if (!state.seriesId || !list.some((s) => s.id === state.seriesId)) {
    const pref = list.find((s) => /^Riz/.test(s.commodity) && s.unit === "KG") || list[0];
    state.seriesId = pref?.id;
  }
  sel.value = state.seriesId;
  if (!D.markets[state.country]) {
    try { D.markets[state.country] = await load(`markets_${state.country}.json`); } catch { D.markets[state.country] = []; }
  }
  renderKpis(); renderEvolution(); renderMap(); renderAlertList(); renderMarkets(); renderComparison();
}

/* ---------- KPI ---------- */
function renderKpis() {
  const iso = state.country;
  const infl = D.inflation.filter((r) => r.country_iso3 === iso);
  const last = infl[infl.length - 1];
  const prev = infl.find((r) => last && r.month_date === shiftMonth(last.month_date, -12));
  const al = D.alerts.filter((a) => a.country_iso3 === iso);
  const hot = al.filter((a) => a.alert_level === "Crise" || a.alert_level === "Alerte").length;
  const c = D.countries.find((x) => x.country_iso3 === iso);
  const latest = countrySeries().map((s) => ({ s, y: s.y[s.y.length - 1], d: s.d[s.d.length - 1] }))
    .filter((x) => x.y != null && x.d === c.last_month).sort((a, b) => b.y - a.y)[0];
  const tiles = [
    ["Inflation des produits suivis (1 an)", last ? fmtPct(last.food_inflation_yoy_pct) : "—",
      last ? `${fmtMonth(last.month_date)}${prev ? ` · il y a un an : ${fmtPct(prev.food_inflation_yoy_pct)}` : ""}` : "Historique insuffisant"],
    ["Marchés suivis", nf().format(c.n_markets), `depuis ${new Date(c.first_month).getFullYear()}`],
    ["Séries en alerte ou crise", nf().format(hot), `sur ${nf().format(al.length)} séries marché × produit`],
    ["Plus forte hausse sur 1 an", latest ? fmtPct(latest.y) : "—", latest ? `${latest.s.commodity}` : "—"],
  ];
  $("kpis").innerHTML = tiles.map(([l, v, f]) =>
    `<div class="kpi"><p class="k-label">${esc(l)}</p><p class="k-value">${esc(v)}</p><p class="k-foot">${esc(f)}</p></div>`).join("");
}
function shiftMonth(d, n) { const x = new Date(d + "T00:00:00"); x.setMonth(x.getMonth() + n); return x.toISOString().slice(0, 10); }

/* ---------- Évolution + prévision ---------- */
function renderEvolution() {
  const s = D.national.find((x) => x.id === state.seriesId);
  const ch = baseChart("chart-evol");
  if (!s) { ch.clear(); return; }
  let start = 0;
  if (state.range) { const cut = shiftMonth(s.d[s.d.length - 1], -state.range); start = s.d.findIndex((d) => d >= cut); }
  const d = s.d.slice(start), p = s.p.slice(start);
  const fc = D.forecast.filter((f) => f.country_iso3 === s.country && f.commodity_fr === s.commodity && f.unit === s.unit && f.currency === s.currency);
  const fd = fc.map((f) => f.month_date);
  const allX = [...d, ...fd];
  const pad = (arr, before) => [...Array(before).fill(null), ...arr];
  const blue = css("--series-1");
  const lastIdx = d.length - 1;
  const fcLine = fc.length ? pad([p[lastIdx], ...fc.map((f) => f.forecast)], lastIdx) : [];
  const lo = fc.length ? pad([p[lastIdx], ...fc.map((f) => f.lower_80)], lastIdx) : [];
  const band = fc.length ? pad([0, ...fc.map((f) => f.upper_80 - f.lower_80)], lastIdx) : [];
  const cur = CUR[s.currency] || s.currency;

  ch.setOption({
    animation: false,
    grid: { left: 64, right: 24, top: 36, bottom: 34 },
    tooltip: {
      ...tooltipBase(), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: css("--axis") } },
      formatter: (ps) => {
        const i = ps[0].dataIndex, x = allX[i];
        const isFc = i > lastIdx;
        const val = isFc ? fc[i - lastIdx - 1] : null;
        let h = `<b>${fmtMonth(x)}</b><br>`;
        if (!isFc) h += `Prix : <b>${fmtPrice(p[i], s.currency)}/${s.unit.toLowerCase()}</b>` + (s.y[start + i] != null ? `<br>Sur 1 an : ${fmtPct(s.y[start + i])}` : "") + `<br><span style="color:${css("--muted")}">${s.nm[start + i]} marché(s)</span>`;
        else h += `Prévision : <b>${fmtPrice(val.forecast, s.currency)}</b><br>Intervalle 80 % : ${fmtPrice(val.lower_80, s.currency)} – ${fmtPrice(val.upper_80, s.currency)}`;
        return h;
      },
    },
    xAxis: { type: "category", data: allX, boundaryGap: false, ...axisCommon(), splitLine: { show: false },
      axisLabel: { ...axisCommon().axisLabel, formatter: (v) => v.slice(0, 7) } },
    yAxis: { type: "value", scale: true, name: `${cur}/${s.unit.toLowerCase()}`, nameTextStyle: { color: css("--muted"), fontSize: 11, align: "left" }, ...axisCommon(),
      axisLine: { show: false }, axisLabel: { ...axisCommon().axisLabel, formatter: (v) => nf().format(v) } },
    series: [
      { name: "Prix", type: "line", data: p, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, color: blue }, itemStyle: { color: blue }, connectNulls: false,
        emphasis: { focus: "none" } },
      { name: "bas", type: "line", data: lo, stack: "band", lineStyle: { opacity: 0 }, showSymbol: false, silent: true },
      { name: "Intervalle 80 %", type: "line", data: band, stack: "band", lineStyle: { opacity: 0 }, showSymbol: false, silent: true,
        areaStyle: { color: blue, opacity: 0.12 } },
      { name: "Prévision", type: "line", data: fcLine, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, type: [6, 4], color: blue }, itemStyle: { color: blue } },
    ],
  }, true);

  $("fc-note").textContent = fc.length
    ? `Prévision : ${fmtPrice(fc[fc.length - 1].forecast, s.currency)}/${s.unit.toLowerCase()} en ${fmtMonth(fd[fd.length - 1])}. Erreur moyenne du modèle sur les 6 derniers mois connus : ${nf(1).format(fc[0].backtest_mape_pct)} %.`
    : "Pas de prévision pour ce produit (historique trop court ou interrompu).";
  $("chart-evol-table").innerHTML = table(["Mois", `Prix (${cur}/${s.unit.toLowerCase()})`, "Sur 1 an", "Marchés"],
    s.d.map((x, i) => [x.slice(0, 7), fmtPrice(s.p[i], s.currency), fmtPct(s.y[i]), s.nm[i]]).reverse(), [1, 2, 3]);
}

function table(head, rows, numCols = []) {
  return `<table><thead><tr>${head.map((h, i) => `<th class="${numCols.includes(i) ? "n" : ""}">${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
    rows.map((r) => `<tr>${r.map((c, i) => `<td class="${numCols.includes(i) ? "n" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("") + "</tbody></table>";
}

/* ---------- Carte ---------- */
function renderMap() {
  if (!map) {
    map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 12,
    }).addTo(map);
    $("map-legend").innerHTML = Object.values(STATUS).map((s) =>
      `<li><span class="badge ${s.label}">${s.icon} ${s.label}</span></li>`).join("");
  }
  if (mapLayer) mapLayer.remove();
  const al = D.alerts.filter((a) => a.country_iso3 === state.country && a.latitude != null);
  const byMarket = {};
  for (const a of al) {
    const k = a.market;
    if (!byMarket[k] || LEVEL_RANK[a.alert_level] > LEVEL_RANK[byMarket[k].worst.alert_level]) byMarket[k] = { ...byMarket[k], worst: a };
    (byMarket[k].items ||= []).push(a);
  }
  mapLayer = L.layerGroup();
  const pts = [];
  for (const [mk, v] of Object.entries(byMarket)) {
    const st = STATUS[v.worst.alert_level];
    const top = v.items.sort((a, b) => b.alert_score - a.alert_score).slice(0, 4);
    const html = `<b>${esc(mk)}</b> <span style="color:#777">${esc(v.worst.region || "")}</span><br>` +
      top.map((a) => `<span class="badge ${a.alert_level}">${STATUS[a.alert_level].icon} ${a.alert_level}</span> ${esc(a.commodity_fr)} : ${fmtPrice(a.price, a.currency)} (${fmtPct(a.deviation_pct)} vs attendu)`).join("<br>");
    L.circleMarker([v.worst.latitude, v.worst.longitude], {
      radius: 8 + LEVEL_RANK[v.worst.alert_level] * 2, color: "#fff", weight: 2, fillColor: st.color, fillOpacity: 0.95,
    }).bindTooltip(html, { sticky: true }).addTo(mapLayer);
    pts.push([v.worst.latitude, v.worst.longitude]);
  }
  mapLayer.addTo(map);
  if (pts.length) map.fitBounds(pts, { padding: [24, 24], maxZoom: 8 });
  const m = al[0]?.month_date;
  $("map-sub").textContent = m ? `Niveau le plus élevé parmi les produits suivis, par marché — ${fmtMonth(m)}.` : "Aucune alerte calculable (historique insuffisant).";
  setTimeout(() => map.invalidateSize(), 50);
}

function renderAlertList() {
  const al = D.alerts.filter((a) => a.country_iso3 === state.country && a.alert_level !== "Normal").slice(0, 25);
  $("alert-list").innerHTML = al.length ? al.map((a) => `
    <div class="alert-row">
      <div><div class="what">${esc(a.commodity_fr)}</div><div class="where">${esc(a.market)}${a.region ? " · " + esc(a.region) : ""}</div></div>
      <div class="num">${fmtPrice(a.price, a.currency)}<small>attendu ${fmtPrice(a.expected_price, a.currency)}</small></div>
      <div class="num"><span class="badge ${a.alert_level}">${STATUS[a.alert_level].icon} ${a.alert_level}</span><small class="up">${fmtPct(a.deviation_pct)}</small></div>
    </div>`).join("") : `<p class="empty">Aucune hausse anormale détectée sur le dernier mois.</p>`;
}

/* ---------- Prix par marché ---------- */
function renderMarkets() {
  const s = D.national.find((x) => x.id === state.seriesId);
  const ch = baseChart("chart-markets");
  if (!s) return ch.clear();
  const ms = (D.markets[state.country] || []).filter((m) => m.commodity === s.commodity && m.unit === s.unit);
  const cutoff = shiftMonth(s.d[s.d.length - 1], -3);
  const rows = ms.map((m) => ({ market: m.market, region: m.region, d: m.d[m.d.length - 1], p: m.p[m.p.length - 1] }))
    .filter((r) => r.d >= cutoff).sort((a, b) => a.p - b.p);
  const shown = rows.slice(-20);
  $("markets-sub").textContent = `${s.commodity} — dernier relevé de chaque marché (3 derniers mois). ${rows.length > 20 ? "20 marchés les plus chers affichés." : ""}`;
  const blue = css("--series-1");
  ch.setOption({
    animation: false, grid: { left: 118, right: 70, top: 6, bottom: 24 },
    tooltip: { ...tooltipBase(), trigger: "item", formatter: (pp) => { const r = shown[pp.dataIndex]; return `<b>${esc(r.market)}</b> (${esc(r.region || "")})<br>${fmtPrice(r.p, s.currency)}/${s.unit.toLowerCase()}<br><span style="color:#888">${fmtMonth(r.d)}</span>`; } },
    xAxis: { type: "value", ...axisCommon(), axisLabel: { ...axisCommon().axisLabel, formatter: (v) => nf().format(v) } },
    yAxis: { type: "category", data: shown.map((r) => r.market), ...axisCommon(), splitLine: { show: false }, axisLabel: { color: css("--text-secondary"), fontSize: 11, width: 104, overflow: "truncate" } },
    series: [{ type: "bar", data: shown.map((r) => r.p), barMaxWidth: 14, itemStyle: { color: blue, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (pp) => nf().format(pp.value) } }],
  }, true);
  $("chart-markets-table").innerHTML = table(["Marché", "Région", "Mois", `Prix (${CUR[s.currency] || s.currency})`],
    rows.slice().reverse().map((r) => [r.market, r.region || "", r.d.slice(0, 7), fmtPrice(r.p, s.currency)]), [3]);
}

/* ---------- Comparaison régionale ---------- */
function renderComparison() {
  const counts = {};
  for (const r of D.comparison) if (r.unit === "KG" || r.unit === "L") counts[r.commodity_fr + "|" + r.unit] = (counts[r.commodity_fr + "|" + r.unit] || 0) + 1;
  const opts = Object.entries(counts).filter(([, n]) => n >= 2).map(([k]) => k).sort((a, b) => a.localeCompare(b, "fr"));
  const sel = $("cmp-commodity");
  if (!opts.length) { sel.innerHTML = ""; baseChart("chart-cmp").clear(); return; }
  sel.innerHTML = opts.map((k) => `<option value="${esc(k)}">${esc(k.replace("|", " — "))}</option>`).join("");
  if (!state.cmp || !opts.includes(state.cmp)) state.cmp = opts.find((k) => /^Riz \(import/.test(k)) || opts[0];
  sel.value = state.cmp;
  sel.onchange = () => { state.cmp = sel.value; renderComparison(); };
  const [name, unit] = state.cmp.split("|");
  const rows = D.comparison.filter((r) => r.commodity_fr === name && r.unit === unit && r.avg_usd_price_12m != null)
    .sort((a, b) => a.avg_usd_price_12m - b.avg_usd_price_12m);
  const blue = css("--series-1"), muted = css("--axis");
  baseChart("chart-cmp").setOption({
    animation: false, grid: { left: 110, right: 70, top: 6, bottom: 24 },
    tooltip: { ...tooltipBase(), trigger: "item", formatter: (pp) => { const r = rows[pp.dataIndex];
      return `<b>${esc(r.country_name)}</b><br>${nf(2).format(r.avg_usd_price_12m)} $/${unit.toLowerCase()}<br>${fmtPrice(r.avg_local_price_12m, r.currency)} en monnaie locale<br>Variation annuelle moyenne : ${fmtPct(r.avg_yoy_pct_12m)}`; } },
    xAxis: { type: "value", ...axisCommon(), axisLabel: { ...axisCommon().axisLabel, formatter: (v) => nf(2).format(v) + " $" } },
    yAxis: { type: "category", data: rows.map((r) => r.country_name), ...axisCommon(), splitLine: { show: false },
      axisLabel: { color: css("--text-secondary"), fontSize: 12, fontWeight: (v) => 400 } },
    series: [{ type: "bar", barMaxWidth: 18,
      data: rows.map((r) => ({ value: r.avg_usd_price_12m, itemStyle: { color: r.country_iso3 === state.country ? blue : muted, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (pp) => nf(2).format(pp.value) + " $" } }],
  }, true);
}

/* ---------- Inflation comparée ---------- */
function renderInflation() {
  const pal = SERIES();
  // La couleur suit le pays (emplacement fixe tant qu'il reste sélectionné), jamais son rang
  state.slots ||= Object.fromEntries(state.inflCountries.map((c, i) => [c, i]));
  const colorOf = Object.fromEntries(state.inflCountries.map((c) => [c, pal[state.slots[c]]]));
  const chips = $("infl-countries");
  chips.innerHTML = D.countries.map((c) => {
    const on = state.inflCountries.includes(c.country_iso3);
    return `<button class="chip ${on ? "on" : ""}" data-c="${c.country_iso3}" aria-pressed="${on}">${on ? `<span class="sw" style="background:${colorOf[c.country_iso3]}"></span>` : ""}${esc(c.country_name)}</button>`;
  }).join("");
  chips.querySelectorAll("button").forEach((b) => b.onclick = () => {
    const c = b.dataset.c, i = state.inflCountries.indexOf(c);
    if (i >= 0) {
      if (state.inflCountries.length > 1) { state.inflCountries.splice(i, 1); delete state.slots[c]; }
    } else {
      if (state.inflCountries.length >= MAX_INFL) { const out = state.inflCountries.shift(); delete state.slots[out]; }
      const used = new Set(Object.values(state.slots));
      state.slots[c] = [0, 1, 2, 3].find((k) => !used.has(k));
      state.inflCountries.push(c);
    }
    renderInflation();
  });
  const months = [...new Set(D.inflation.filter((r) => state.inflCountries.includes(r.country_iso3)).map((r) => r.month_date))].sort();
  const series = state.inflCountries.map((iso) => {
    const m = Object.fromEntries(D.inflation.filter((r) => r.country_iso3 === iso).map((r) => [r.month_date, r.food_inflation_yoy_pct]));
    const name = D.countries.find((c) => c.country_iso3 === iso).country_name;
    const data = months.map((d) => m[d] ?? null);
    let lastI = data.length - 1; while (lastI >= 0 && data[lastI] == null) lastI--;
    return { name, type: "line", data, showSymbol: false, symbolSize: 8, connectNulls: false,
      lineStyle: { width: 2, color: colorOf[iso] }, itemStyle: { color: colorOf[iso] } };
  });
  baseChart("chart-infl").setOption({
    animation: false, grid: { left: 52, right: 24, top: 34, bottom: 30 },
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-secondary") } },
    tooltip: { ...tooltipBase(), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: css("--axis") } },
      valueFormatter: (v) => fmtPct(v) },
    xAxis: { type: "category", data: months, boundaryGap: false, ...axisCommon(), splitLine: { show: false },
      axisLabel: { ...axisCommon().axisLabel, formatter: (v) => v.slice(0, 7) } },
    yAxis: { type: "value", ...axisCommon(), axisLine: { show: false }, axisLabel: { ...axisCommon().axisLabel, formatter: (v) => v + " %" } },
    series: [...series, { type: "line", data: [], markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: css("--axis"), type: "solid" }, label: { show: false } } }],
  }, true);
}

/* ---------- Agent IA ---------- */
const SUGGESTIONS = [
  "Quel est le prix du riz importé à Thiès ce mois-ci ?",
  "Quels produits ont le plus augmenté au Sénégal sur un an ?",
  "Compare le prix du riz importé entre le Sénégal, le Mali et la Mauritanie",
  "Montre l'évolution du prix du mil à Kaolack depuis 2020",
  "Quels marchés sont en crise ou en alerte en ce moment ?",
  "Que prévoit le modèle pour le prix du riz dans les 3 prochains mois ?",
];
const history = [];

function setupAgent() {
  $("suggest").innerHTML = SUGGESTIONS.map((s) => `<button type="button">${esc(s)}</button>`).join("");
  $("suggest").querySelectorAll("button").forEach((b) => b.onclick = () => { $("q").value = b.textContent; $("ask").requestSubmit(); });
  $("ask").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("q").value.trim();
    if (!q) return;
    $("q").value = "";
    addMsg("user", `<p>${esc(q)}</p>`);
    const pending = addMsg("bot", PENDING_HTML);
    let step = 0;
    const timer = setInterval(() => { const t = pending.querySelector("#thinking-step"); if (t && step < STEPS.length - 1) t.textContent = STEPS[++step]; }, 2500);
    const btn = $("ask").querySelector("button"); btn.disabled = true;
    try {
      const r = await fetch("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, history }) });
      const out = await r.json();
      if (!r.ok) throw new Error(out.error || r.statusText);
      history.push({ role: "user", content: q }, { role: "assistant", content: out.answer });
      renderAnswer(pending, out, q);
    } catch (err) {
      pending.innerHTML = `<div class="bot-head"><span class="avatar" aria-hidden="true">IA</span><span class="bot-name">Analyste IA</span></div>
        <div class="bot-body"><p class="error">L'analyse n'a pas abouti : ${esc(err.message)}</p></div>`;
    } finally { clearInterval(timer); btn.disabled = false; $("q").focus(); }
  };
}

function addMsg(who, html) {
  const div = document.createElement("div");
  div.className = `msg ${who}`; div.innerHTML = html;
  $("chat").appendChild(div); div.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return div;
}

const PENDING_HTML = `<div class="bot-head"><span class="avatar" aria-hidden="true">IA</span><span class="bot-name">Analyste IA</span></div>
  <div class="bot-body"><div class="typing"><span></span><span></span><span></span></div><p class="thinking" id="thinking-step">Lecture de la question…</p></div>`;
const STEPS = ["Lecture de la question…", "Recherche des produits et des marchés…", "Interrogation de la base de données…", "Calcul des indicateurs…", "Rédaction de la synthèse…"];

/* Markdown sûr : titres, gras, italique, code, listes, tableaux */
function inline(t) {
  return t.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
}
const isNum = (c) => /^[\s≈~<>±+\-−–]*[\d.,\s]+(\s?(%|FCFA|XOF|MRU|GMD|GNF|\$|USD)(\/\w+)?)?(\s*\(.*\))?\s*$/.test(c);
function md(text) {
  const lines = esc(text).replace(/\r/g, "").split("\n");
  const out = []; let para = []; let list = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flushPara(); flushList();
      const head = cells(l); i += 1; const rows = [];
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) { i += 1; rows.push(cells(lines[i])); }
      const numCol = head.map((_, c) => c > 0 && rows.length && rows.every((r) => !r[c] || isNum(r[c].replace(/<[^>]+>|\*\*/g, ""))));
      out.push(`<div class="md-table"><table><thead><tr>${head.map((h, c) => `<th class="${numCol[c] ? "n" : ""}">${inline(h)}</th>`).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${head.map((_, c) => `<td class="${numCol[c] ? "n" : ""}">${inline(r[c] ?? "")}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
      continue;
    }
    let m;
    if ((m = l.match(/^\s*(#{1,4})\s+(.*)$/))) { flushPara(); flushList(); out.push(`<h4>${inline(m[2])}</h4>`); continue; }
    if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) { flushPara(); if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) { flushPara(); if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; } list.items.push(m[1]); continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { flushPara(); flushList(); continue; }
    if (!l.trim()) { flushPara(); flushList(); continue; }
    if (list && /^\s{2,}\S/.test(l)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
    flushList(); para.push(l.trim());
  }
  flushPara(); flushList();
  return out.join("");
}

function renderAnswer(el, out, question) {
  const nq = out.queries?.length || 0;
  el.innerHTML = `
    <div class="bot-head">
      <span class="avatar" aria-hidden="true">IA</span><span class="bot-name">Analyste IA</span>
      <span class="bot-meta">${nq ? `${nq} requête${nq > 1 ? "s" : ""} sur la base` : ""}</span>
      <button type="button" class="icon-btn" data-copy title="Copier la réponse">Copier</button>
    </div>
    <div class="bot-body md">${md(out.answer || "Aucune réponse.")}</div>`;
  const body = el.querySelector(".bot-body");
  (out.charts || []).forEach((spec) => {
    const q = out.queries[spec.query_index]; if (!q) return;
    const div = document.createElement("div"); div.className = "bot-chart"; body.appendChild(div);
    drawAgentChart(div, spec, q);
  });
  const foot = document.createElement("div"); foot.className = "bot-foot";
  foot.innerHTML = `<span>Source : WFP / HDX · données jusqu'à ${fmtMonth(D.meta.last_month)}</span>` +
    (nq ? `<details><summary>Afficher le SQL</summary>${out.queries.map((q, i) =>
      `<div class="sql"><div class="sql-purpose">${i + 1}. ${esc(q.purpose)}</div><pre>${esc(q.sql.trim())}</pre></div>`).join("")}</details>` : "");
  el.appendChild(foot);
  el.querySelector("[data-copy]").onclick = (e) => {
    navigator.clipboard?.writeText(out.answer || "").then(() => { e.target.textContent = "Copié"; setTimeout(() => (e.target.textContent = "Copier"), 1500); });
  };
}

function drawAgentChart(div, spec, q) {
  const xi = q.columns.indexOf(spec.x), yi = q.columns.indexOf(spec.y), si = spec.series ? q.columns.indexOf(spec.series) : -1;
  const title = document.createElement("div"); title.className = "bot-chart-title";
  title.textContent = spec.title; div.before(title);
  const ch = echarts.init(div, null, { renderer: "svg" });
  window.addEventListener("resize", () => ch.resize());
  const pal = SERIES();
  const xs = [...new Set(q.rows.map((r) => r[xi]))];
  if (spec.type === "line") xs.sort();
  let groups = si >= 0 ? [...new Set(q.rows.map((r) => r[si]))] : [spec.y];
  const folded = groups.length > 4; if (folded) { groups = groups.slice(0, 4); title.textContent += " (4 premières séries)"; }
  const series = groups.map((g, gi) => {
    const m = new Map(q.rows.filter((r) => si < 0 || r[si] === g).map((r) => [r[xi], r[yi]]));
    return { name: String(g), type: spec.type, data: xs.map((x) => m.get(x) ?? null), showSymbol: false, symbolSize: 8, barMaxWidth: 22,
      lineStyle: { width: 2 }, itemStyle: { color: pal[gi], borderRadius: spec.type === "bar" ? [4, 4, 0, 0] : 0 } };
  });
  ch.setOption({
    animation: false, color: pal,
    legend: groups.length > 1 ? { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-secondary") } } : undefined,
    grid: { left: 60, right: 20, top: groups.length > 1 ? 30 : 12, bottom: 30 },
    tooltip: { ...tooltipBase(), trigger: spec.type === "line" ? "axis" : "item", valueFormatter: (v) => v == null ? "—" : nf(1).format(v) },
    xAxis: { type: "category", data: xs, ...axisCommon(), splitLine: { show: false },
      axisLabel: { ...axisCommon().axisLabel, formatter: (v) => /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.slice(0, 7) : v } },
    yAxis: { type: "value", scale: spec.type === "line", ...axisCommon(), axisLine: { show: false } },
    series,
  });
}

init().catch((e) => {
  document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="card span-2">Impossible de charger les données (${esc(e.message)}).</p>`);
  console.error(e);
});
