"use strict";

// ------------------------------------------------------------------ utilitaires
const $ = (sel, el = document) => el.querySelector(sel);
const view = $("#view");
const SETUPS = {
  pullback: "Pullback dans la tendance",
  breakout_retest: "Cassure + retest",
  divergence: "Retournement sur divergence RSI",
};
const WATCH_KINDS = { pullback: "Repli vers un niveau", breakout: "Test de niveau", oversold: "Excès" };

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(v, max = 5) {
  return v == null ? "–" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: max });
}
function pct(v) {
  if (v == null) return `<span class="muted">–</span>`;
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  return `<span class="${cls}">${v > 0 ? "+" : ""}${num(v, 1)} %</span>`;
}
function trendBadge(label) {
  const cls = label === "haussière" ? "long" : label === "baissière" ? "short" : "";
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}
function dirBadge(d) {
  return `<span class="badge ${d}">${d === "long" ? "Achat" : "Vente"}</span>`;
}
function star(on) {
  return `<span class="star ${on ? "on" : ""}" title="${on ? "Favori" : ""}">${on ? "★" : "☆"}</span>`;
}
const assetLink = sym => `#/actif/${encodeURIComponent(sym)}`;
function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" }) : "";
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join(", ") : r.statusText);
  }
  return body;
}

function showStatus(msg, isError = false) {
  const el = $("#status");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.className = "status" + (isError ? " error" : "");
}
function loading() {
  view.innerHTML = `<div class="empty">Chargement…</div>`;
}
function bindRowLinks(root = view) {
  root.querySelectorAll("[data-sym]").forEach(el =>
    el.addEventListener("click", e => {
      if (e.target.closest("button, a")) return;
      location.hash = assetLink(el.dataset.sym);
    }));
}

// ------------------------------------------------------------------ régime de marché (en-tête)
async function loadRegime() {
  try {
    const m = await api("/api/macro");
    const r = m.regime;
    const el = $("#regime");
    el.textContent = r.available ? `Marché ${r.label}` : "Macro : pas de données";
    el.className = "badge " + (r.label === "risk-on" ? "on" : r.label === "risk-off" ? "off" : "");
    return m;
  } catch { return null; }
}

// ------------------------------------------------------------------ écran Recommandations
function signalCard(s) {
  return `
    <a class="card signal-link" href="${assetLink(s.symbol)}">
      <div class="row spread">
        <div class="row">${s.favorite ? star(true) : ""}<strong>${esc(s.name)}</strong><span class="muted">${esc(s.symbol)}</span></div>
        ${dirBadge(s.direction)}
      </div>
      <div class="muted">${esc(SETUPS[s.setup_type] || s.setup_type)} · confiance ${esc(s.confidence.toLowerCase())}</div>
      <div class="row spread" style="margin-top:.4rem"><span>Score de confluence</span><strong>${s.score}/100</strong></div>
      <div class="score"><i style="width:${s.score}%"></i></div>
      <dl class="kv">
        <dt>Zone d'entrée</dt><dd>${num(s.entry_low)} – ${num(s.entry_high)}</dd>
        <dt>Stop</dt><dd class="down">${num(s.stop)}</dd>
        <dt>Objectifs</dt><dd class="up">${num(s.tp1)} · ${num(s.tp2)} · ${num(s.tp3)}</dd>
        <dt>R:R (TP1)</dt><dd>${num(s.rr_tp1, 2)}</dd>
        <dt>Horizon</dt><dd>${esc(s.horizon)}</dd>
      </dl>
      ${s.warnings.length ? `<div class="row" style="margin-top:.5rem"><span class="badge warn">⚠ ${s.warnings.length} alerte(s)</span></div>` : ""}
    </a>`;
}

function momentumTable(list, title, empty) {
  return `
    <div>
      <h3>${title}</h3>
      ${list.length ? `<table><thead><tr><th>Produit</th><th class="num">3 mois</th><th class="num">6 mois</th><th class="num hide-sm">RSI</th></tr></thead>
        <tbody>${list.map(x => `<tr data-sym="${esc(x.symbol)}"><td><strong>${esc(x.name)}</strong></td>
          <td class="num">${pct(x.perf.m3)}</td><td class="num">${pct(x.perf.m6)}</td><td class="num hide-sm">${num(x.rsi14, 0)}</td></tr>`).join("")}
        </tbody></table>` : `<p class="muted">${empty}</p>`}
    </div>`;
}

const watchItem = w => `
  <li data-sym="${esc(w.symbol)}">
    <div class="row spread"><div class="row">${w.favorite ? star(true) : ""}<strong>${esc(w.name)}</strong>
      <span class="muted">${esc(WATCH_KINDS[w.kind])}</span></div>${dirBadge(w.direction)}</div>
    <div class="muted">${esc(w.message)}</div>
  </li>`;

let homeTab = "stock_us";

async function renderHome() {
  loading();
  const [sig, macro, reco] = await Promise.all([api("/api/signals"), loadRegime(), api("/api/recommendations")]);
  const notes = macro?.regime?.notes || [];
  const strong = sig.signals.filter(s => s.score >= 60);
  const weak = sig.signals.filter(s => s.score < 60);
  const groups = reco.momentum;
  if (!groups[homeTab]) homeTab = Object.keys(groups)[0];

  view.innerHTML = `
    <section class="stack">
      <div class="card">
        <h2>Contexte de marché</h2>
        ${notes.length ? `<ul class="plain">${notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`
                       : `<p class="muted">Aucune donnée macro. Clique sur « Mettre à jour ».</p>`}
      </div>

      <h2>Trades à considérer <span class="muted">(${strong.length} sur ${reco.scanned} produits analysés)</span></h2>
      ${strong.length ? `<div class="grid">${strong.map(signalCard).join("")}</div>`
        : `<div class="card empty">Aucun setup avec un score d'au moins 60 aujourd'hui. Le moteur rejette tout trade dont
             le gain potentiel est inférieur à 2 fois le risque : patience, c'est aussi ça le swing trading.</div>`}
      ${weak.length ? `<details class="card"><summary><strong>Setups plus fragiles</strong> <span class="muted">(${weak.length}, score &lt; 60 : contre-tendance ou contexte défavorable)</span></summary>
          <div class="grid" style="margin-top:12px">${weak.map(signalCard).join("")}</div></details>` : ""}

      <div class="card">
        <h2>À surveiller <span class="muted">(setups en approche : place une alerte)</span></h2>
        ${reco.watch.length ? `<ul class="watch">${reco.watch.slice(0, 10).map(watchItem).join("")}</ul>
          ${reco.watch.length > 10 ? `<details><summary class="muted" style="cursor:pointer;margin-top:.5rem">Voir les ${reco.watch.length - 10} autres</summary>
            <ul class="watch">${reco.watch.slice(10).map(watchItem).join("")}</ul></details>` : ""}`
          : `<p class="muted">Rien de proche d'un niveau clé pour l'instant.</p>`}
      </div>

      <div class="card">
        <h2>Leaders et retardataires</h2>
        <p class="muted" style="margin-top:0">Les plus fortes tendances (achat dans les replis) et les plus faibles (vente sur rebonds), sur 3 et 6 mois.</p>
        <div class="chips" id="momTabs">${Object.entries(groups).map(([k, g]) =>
          `<button type="button" data-k="${k}" class="${k === homeTab ? "active" : ""}">${esc(g.label)}</button>`).join("")}</div>
        <div class="grid" id="momBody" style="margin-top:12px">
          ${momentumTable(groups[homeTab].leaders, "Leaders (tendance haussière)", "Aucun leader en tendance haussière nette.")}
          ${momentumTable(groups[homeTab].laggards, "Retardataires (tendance baissière)", "Aucun produit en tendance baissière nette.")}
        </div>
      </div>

      ${reco.upcoming_events.length ? `<div class="card"><h2>Publications de résultats (14 jours)</h2>
        <ul class="plain">${reco.upcoming_events.map(e => `<li><a href="${assetLink(e.symbol)}"><strong>${fmtDate(e.date)}</strong> · ${esc(e.title)}</a></li>`).join("")}</ul>
        <p class="muted" style="margin:.4rem 0 0">Évite d'ouvrir une position juste avant : le cours peut faire un saut (gap) au-delà de ton stop.</p></div>` : ""}
    </section>`;

  $("#momTabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-k]");
    if (!b) return;
    homeTab = b.dataset.k;
    $("#momTabs").querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    $("#momBody").innerHTML = momentumTable(groups[homeTab].leaders, "Leaders (tendance haussière)", "Aucun leader en tendance haussière nette.")
      + momentumTable(groups[homeTab].laggards, "Retardataires (tendance baissière)", "Aucun produit en tendance baissière nette.");
    bindRowLinks($("#momBody"));
  });
  bindRowLinks();
}

// ------------------------------------------------------------------ écran Marchés (+ recherche)
let marketFilter = "Favoris";

function marketRow(r) {
  if (r.error) return `<tr data-sym="${esc(r.symbol)}"><td>${star(r.favorite)} ${esc(r.name)}</td><td colspan="6" class="muted">${esc(r.error)}</td></tr>`;
  const sig = r.signals?.[0];
  return `<tr data-sym="${esc(r.symbol)}">
    <td>${star(r.favorite)} <strong>${esc(r.name)}</strong><br><span class="muted">${esc(r.symbol)}</span></td>
    <td class="num">${num(r.last_close)}<br>${pct(r.change_pct)}</td>
    <td class="num hide-sm">${pct(r.perf?.m1)}</td><td class="num">${pct(r.perf?.m3)}</td><td class="num hide-sm">${pct(r.perf?.ytd)}</td>
    <td>${trendBadge(r.weekly_trend)}</td>
    <td>${sig ? `${dirBadge(sig.direction)} ${sig.score}` : r.watch?.length ? `<span class="badge warn">à surveiller</span>` : `<span class="muted">–</span>`}</td>
  </tr>`;
}

async function renderMarkets() {
  loading();
  const rows = await api("/api/overview");
  const cats = ["Favoris", "Tous", ...new Set(rows.map(r => r.category))];
  if (!cats.includes(marketFilter)) marketFilter = "Favoris";

  view.innerHTML = `
    <section class="stack">
      <div class="card">
        <h2>Rechercher un produit</h2>
        <form id="searchForm" class="row">
          <input id="q" type="search" placeholder="Nom ou code : Total, BMW, Uranium, ETF MSCI, USDMXN…" autocomplete="off" style="flex:1;min-width:0">
          <button class="btn" type="submit">Chercher</button>
        </form>
        <div id="searchResults"></div>
      </div>
      <div class="chips" id="cats">${cats.map(c => `<button type="button" data-c="${esc(c)}" class="${c === marketFilter ? "active" : ""}">${esc(c)}</button>`).join("")}</div>
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>Produit</th><th class="num">Dernier</th><th class="num hide-sm">1 mois</th><th class="num">3 mois</th>
          <th class="num hide-sm">Depuis 1er janv.</th><th>Tendance hebdo</th><th>Signal</th></tr></thead>
        <tbody id="marketBody"></tbody></table></div></div>
    </section>`;

  const fill = () => {
    const list = marketFilter === "Favoris" ? rows.filter(r => r.favorite)
      : marketFilter === "Tous" ? rows : rows.filter(r => r.category === marketFilter);
    $("#marketBody").innerHTML = list.length ? list.map(marketRow).join("")
      : `<tr><td colspan="7" class="empty">Aucun produit. Ouvre une fiche et touche ☆ pour l'ajouter aux favoris.</td></tr>`;
    bindRowLinks($("#marketBody"));
  };
  fill();
  $("#cats").addEventListener("click", e => {
    const b = e.target.closest("button[data-c]");
    if (!b) return;
    marketFilter = b.dataset.c;
    $("#cats").querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    fill();
  });
  $("#searchForm").addEventListener("submit", async e => {
    e.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return;
    const box = $("#searchResults");
    box.innerHTML = `<p class="muted">Recherche…</p>`;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
      box.innerHTML = (r.tracked.length || r.results.length) ? `<ul class="results">
        ${r.tracked.map(x => `<li><a href="${assetLink(x.symbol)}"><strong>${esc(x.name)}</strong> <span class="muted">${esc(x.provider_symbol)} · ${esc(x.category)}</span></a><span class="badge">suivi</span></li>`).join("")}
        ${r.results.map(x => `<li><div><strong>${esc(x.name)}</strong> <span class="muted">${esc(x.provider_symbol)} · ${esc(x.quote_type || "")} · ${esc(x.exchange || "")}</span></div>
          <button type="button" class="btn ghost" data-add="${esc(x.provider_symbol)}" data-name="${esc(x.name)}">Ajouter</button></li>`).join("")}
      </ul>` : `<p class="muted">Aucun résultat pour « ${esc(q)} ».</p>`;
    } catch (err) { box.innerHTML = `<p class="down">${esc(err.message)}</p>`; }
  });
  $("#searchResults").addEventListener("click", async e => {
    const b = e.target.closest("button[data-add]");
    if (!b) return;
    b.disabled = true;
    b.textContent = "Ajout… (10 s)";
    try {
      const r = await api("/api/assets", { method: "POST", body: JSON.stringify({ provider_symbol: b.dataset.add, name: b.dataset.name }) });
      location.hash = assetLink(r.symbol);
    } catch (err) {
      b.disabled = false;
      b.textContent = "Ajouter";
      showStatus(err.message, true);
    }
  });
}

// ------------------------------------------------------------------ écran Actif
let chart = null;

async function drawChart(symbol, tf, analysis) {
  const box = $("#chart");
  if (!box || !window.LightweightCharts) {
    if (box) box.innerHTML = `<div class="empty">Graphique indisponible (pas de connexion internet ?)</div>`;
    return;
  }
  if (chart) { chart.remove(); chart = null; }
  const data = await api(`/api/prices/${encodeURIComponent(symbol)}?tf=${tf}&limit=${tf === "4H" ? 600 : 400}`);
  const css = getComputedStyle(document.documentElement);
  const c = v => css.getPropertyValue(v).trim();
  chart = LightweightCharts.createChart(box, {
    autoSize: true,
    layout: { background: { color: c("--surface") }, textColor: c("--muted") },
    grid: { vertLines: { color: c("--border") }, horzLines: { color: c("--border") } },
    rightPriceScale: { borderColor: c("--border") },
    timeScale: { borderColor: c("--border"), timeVisible: tf === "4H" },
    // La molette et le glissé vertical font défiler la page, pas le graphique
    handleScroll: { mouseWheel: false, vertTouchDrag: false },
    handleScale: { mouseWheel: false },
  });
  const px = analysis.last_close;
  const precision = analysis.asset_class === "forex" ? (analysis.symbol.includes("JPY") ? 3 : 5)
    : px < 1 ? 5 : px < 10 ? 4 : 2;
  const candles = chart.addCandlestickSeries({
    upColor: c("--up"), downColor: c("--down"), wickUpColor: c("--up"), wickDownColor: c("--down"), borderVisible: false,
    priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision },
  });
  candles.setData(data.candles);
  const colors = { sma20: "#f0b429", sma50: "#4c9aff", sma200: "#b07cff" };
  for (const [k, pts] of Object.entries(data.overlays)) {
    const s = chart.addLineSeries({ color: colors[k], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    s.setData(pts);
  }
  if (tf === "1D" || tf === "4H") {
    analysis.zones.forEach(z => candles.createPriceLine({
      price: z.mid, color: z.kind === "support" ? "rgba(38,166,154,.55)" : z.kind === "resistance" ? "rgba(239,83,80,.55)" : "rgba(139,152,165,.6)",
      lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: false,
    }));
  }
  const s = analysis.signals[0];
  if (s) {
    const line = (price, color, title) => candles.createPriceLine({ price, color, lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, title });
    line(s.entry_ref, c("--accent"), "Entrée");
    line(s.stop, c("--down"), "Stop");
    line(s.tp1, c("--up"), "TP1");
    line(s.tp2, c("--up"), "TP2");
  }
  chart.timeScale().fitContent();
}

function tradeCard(s, sizing) {
  const b = s.score_breakdown, m = s.score_max;
  const labels = { tendance: "Tendance", setup: "Setup", rr: "R:R", macro: "Macro", momentum: "Momentum" };
  let size = `<p class="muted">Calcul de taille indisponible.</p>`;
  if (sizing?.error) size = `<p class="down">${esc(sizing.error)}</p>`;
  else if (sizing) size = `
    <dl class="kv">
      <dt>Quantité</dt><dd><strong>${num(sizing.units, 4)} ${esc(sizing.unit_label)}</strong></dd>
      ${sizing.detail ? `<dt>Détail</dt><dd>${esc(sizing.detail)}</dd>` : ""}
      <dt>Risque si stop touché</dt><dd class="down">${num(sizing.risk_real, 2)} ${esc(sizing.account_currency)} (${num(sizing.risk_pct, 2)} %)</dd>
      <dt>Valeur de la position</dt><dd>${num(sizing.position_value, 0)} ${esc(sizing.account_currency)}</dd>
      <dt>Effet de levier</dt><dd>${num(sizing.leverage, 2)}×</dd>
    </dl>
    ${sizing.warnings.length ? `<ul class="plain warn-list">${sizing.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}`;

  return `
    <article class="card">
      <div class="row spread">
        <h2>${dirBadge(s.direction)} ${esc(s.setup_label)}</h2>
        <strong>${s.score}/100</strong>
      </div>
      <div class="score"><i style="width:${s.score}%"></i></div>
      <div class="breakdown">${Object.keys(labels).map(k => `<div><div class="muted">${labels[k]}</div>${b[k]}/${m[k]}</div>`).join("")}</div>
      <div class="grid" style="margin-top:.8rem">
        <div>
          <h3>Plan de trade</h3>
          <dl class="kv">
            <dt>Zone d'entrée</dt><dd>${num(s.entry_low)} – ${num(s.entry_high)}</dd>
            <dt>Entrée de référence</dt><dd>${num(s.entry_ref)}</dd>
            <dt>Type d'ordre</dt><dd>${esc(s.order_type)}</dd>
            <dt>Stop</dt><dd class="down">${num(s.stop)}</dd>
            <dt>TP1 (1/3)</dt><dd class="up">${num(s.tp1)} · R:R ${num(s.rr_tp1, 2)}</dd>
            <dt>TP2 (1/3)</dt><dd class="up">${num(s.tp2)} · R:R ${num(s.rr_tp2, 2)}</dd>
            <dt>TP3</dt><dd class="up">${num(s.tp3)}</dd>
            <dt>Horizon</dt><dd>${esc(s.horizon)}</dd>
            <dt>Confirmation H4</dt><dd>${s.h4_confirmation ? "Oui" : "Pas encore"}</dd>
          </dl>
          <p class="muted" style="margin:.5rem 0 0">${esc(s.trailing)}</p>
        </div>
        <div>
          <h3>Taille de position</h3>
          ${size}
        </div>
      </div>
      <div class="rationale">${esc(s.rationale)}</div>
      <h3 style="margin-top:.8rem">Le scénario est invalidé si…</h3>
      <ul class="plain">${s.invalidation.map(i => `<li>${esc(i)}</li>`).join("")}</ul>
      ${s.warnings.length ? `<h3 style="margin-top:.8rem">Alertes</h3><ul class="plain warn-list">${s.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    </article>`;
}

async function loadNews(symbol) {
  const box = $("#news");
  if (!box) return;
  try {
    const items = await api(`/api/news/${encodeURIComponent(symbol)}`);
    box.innerHTML = items.length ? `<ul class="news">${items.map(n => `
      <li><a href="${esc(n.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>
        <div class="muted">${esc(n.source || "")}${n.published ? " · " + fmtDate(n.published) : ""}</div></li>`).join("")}</ul>`
      : `<p class="muted">Aucune actualité récente trouvée.</p>`;
  } catch { box.innerHTML = `<p class="muted">Actualités indisponibles.</p>`; }
}

async function renderAsset(symbol) {
  loading();
  const a = await api(`/api/analysis/${encodeURIComponent(symbol)}`);
  if (a.error) {
    view.innerHTML = `<div class="card empty">${esc(a.error)}</div>`;
    return;
  }
  const sizings = await Promise.all(a.signals.map(s =>
    api("/api/size", { method: "POST", body: JSON.stringify({ symbol, entry: s.entry_ref, stop: s.stop }) })
      .catch(e => ({ error: e.message }))));
  const i = a.indicators, p = a.perf;

  view.innerHTML = `
    <section class="stack">
      <div class="row spread">
        <div>
          <div class="row">
            <h1 style="font-size:1.4rem">${esc(a.name)} <span class="muted" style="font-size:1rem">${esc(a.symbol)}</span></h1>
            <button type="button" id="favBtn" class="icon-btn" aria-label="Favori">${star(a.favorite)}</button>
          </div>
          <div class="row"><strong style="font-size:1.2rem">${num(a.last_close)} ${esc(a.currency)}</strong>${pct(a.change_pct)}
            <span class="muted">clôture du ${new Date(a.bar_date).toLocaleDateString("fr-FR")} · ${esc(a.category)}</span></div>
        </div>
        <div class="tf" id="tf">${["1M", "1W", "1D", "4H"].map(t => `<button type="button" data-tf="${t}" class="${t === "1D" ? "active" : ""}">${t}</button>`).join("")}</div>
      </div>
      <div class="perf-row">
        ${[["1 mois", p.m1], ["3 mois", p.m3], ["6 mois", p.m6], ["1 an", p.y1], ["Depuis 1er janv.", p.ytd]].map(([l, v]) =>
          `<div><div class="muted">${l}</div>${pct(v)}</div>`).join("")}
      </div>
      <div class="card" style="padding:6px"><div id="chart"></div></div>
      <p class="muted" style="margin:0;font-size:.8rem">Jaune : MM20 · bleu : MM50 · violet : MM200 · pointillés : supports (vert) et résistances (rouge).</p>

      ${a.signals.length ? a.signals.map((s, k) => tradeCard(s, sizings[k])).join("")
        : `<div class="card"><h2>Pas de setup valide aujourd'hui</h2>
             ${a.rejected.length ? `<p class="muted">Setups repérés mais rejetés :</p><ul class="plain">${a.rejected.map(r => `<li>${esc(r)}</li>`).join("")}</ul>`
               : `<p class="muted">Aucune configuration intéressante. On attend que le marché vienne à nous.</p>`}</div>`}

      ${a.watch.length ? `<div class="card"><h2>À surveiller</h2><ul class="plain">${a.watch.map(w =>
        `<li>${dirBadge(w.direction)} ${esc(w.message)}</li>`).join("")}</ul></div>` : ""}

      <div class="grid">
        <div class="card">
          <h2>Tendance hebdomadaire ${trendBadge(a.weekly_trend.label)}</h2>
          <ul class="plain">${a.weekly_trend.details.map(d => `<li>${esc(d)}</li>`).join("")}</ul>
        </div>
        <div class="card">
          <h2>Tendance journalière ${trendBadge(a.daily_trend.label)}</h2>
          <ul class="plain">${a.daily_trend.details.map(d => `<li>${esc(d)}</li>`).join("")}</ul>
        </div>
        <div class="card">
          <h2>Indicateurs</h2>
          <dl class="kv">
            <dt>RSI 14</dt><dd>${num(i.rsi14, 1)}</dd>
            <dt>ATR 14</dt><dd>${num(i.atr14)} (${num(i.atr_pct, 2)} %)</dd>
            <dt>ADX</dt><dd>${num(i.adx, 1)}</dd>
            <dt>MM20 / MM50 / MM200</dt><dd>${num(i.sma20)} / ${num(i.sma50)} / ${num(i.sma200)}</dd>
          </dl>
        </div>
        <div class="card">
          <h2>Macro <span class="badge ${a.macro.bias > 0.25 ? "long" : a.macro.bias < -0.25 ? "short" : ""}">biais ${num(a.macro.bias, 2)}</span></h2>
          <ul class="plain">${a.macro.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
          ${a.events.length ? `<h3 style="margin-top:.6rem">Événements à venir</h3><ul class="plain">${a.events.map(e => `<li>${new Date(e.date).toLocaleDateString("fr-FR")} : ${esc(e.title)}</li>`).join("")}</ul>` : ""}
        </div>
        <div class="card">
          <h2>Zones clés</h2>
          <dl class="kv">${[...a.zones].reverse().map(z => `
            <dt class="${z.kind === "support" ? "up" : z.kind === "resistance" ? "down" : ""}">${z.kind === "support" ? "Support" : z.kind === "resistance" ? "Résistance" : "Pivot"}</dt>
            <dd>${num(z.low)} – ${num(z.high)} <span class="muted">(${z.touches} contact${z.touches > 1 ? "s" : ""})</span></dd>`).join("")}
          </dl>
        </div>
        <div class="card">
          <h2>Actualités</h2>
          <div id="news"><p class="muted">Chargement…</p></div>
        </div>
      </div>
      ${a.origin === "perso" ? `<div><button type="button" class="btn ghost" id="removeBtn">Retirer ce produit du suivi</button></div>` : ""}
    </section>`;

  $("#tf").addEventListener("click", e => {
    const b = e.target.closest("button[data-tf]");
    if (!b) return;
    $("#tf").querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    drawChart(symbol, b.dataset.tf, a).catch(err => showStatus(err.message, true));
  });
  $("#favBtn").addEventListener("click", async () => {
    try {
      a.favorite = !a.favorite;
      await api(`/api/favorites/${encodeURIComponent(symbol)}`, { method: a.favorite ? "POST" : "DELETE" });
      $("#favBtn").innerHTML = star(a.favorite);
      showStatus(a.favorite ? "Ajouté aux favoris : graphique H4 mis à jour chaque soir." : "Retiré des favoris.");
      setTimeout(() => showStatus(""), 2500);
    } catch (err) { showStatus(err.message, true); }
  });
  $("#removeBtn")?.addEventListener("click", async () => {
    if (!confirm(`Retirer ${a.name} du suivi ?`)) return;
    await api(`/api/assets/${encodeURIComponent(symbol)}`, { method: "DELETE" });
    location.hash = "#/marches";
  });
  loadNews(symbol);
  await drawChart(symbol, "1D", a);
}

// ------------------------------------------------------------------ écran Réglages
async function renderSettings() {
  loading();
  const st = await api("/api/settings");
  view.innerHTML = `
    <section class="card">
      <h2>Mon compte</h2>
      <p class="muted">Utilisé pour calculer la taille de chaque position.</p>
      <form class="settings" id="settingsForm">
        <label>Capital
          <input name="capital" type="number" min="1" step="any" value="${st.capital}" required></label>
        <label>Devise du compte
          <select name="account_currency">${["EUR", "USD"].map(c => `<option ${c === st.account_currency ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <label>Risque par trade (% du capital, max ${st.max_risk_pct} %)
          <input name="risk_pct" type="number" min="0.1" max="${st.max_risk_pct}" step="0.1" value="${st.risk_pct}" required></label>
        <label>Risque total ouvert maximum (%)
          <input name="max_open_risk_pct" type="number" min="1" max="20" step="0.5" value="${st.max_open_risk_pct}" required></label>
        <div><button class="btn" type="submit">Enregistrer</button></div>
      </form>
    </section>`;
  $("#settingsForm").addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    ["capital", "risk_pct", "max_open_risk_pct"].forEach(k => (body[k] = Number(body[k])));
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
      showStatus("Réglages enregistrés.");
      setTimeout(() => showStatus(""), 2500);
    } catch (err) { showStatus(err.message, true); }
  });
}

// ------------------------------------------------------------------ mise à jour des données
async function refreshData() {
  const btn = $("#refreshBtn");
  btn.disabled = true;
  try {
    const before = (await api("/api/refresh/status")).finished_at;
    await api("/api/refresh", { method: "POST" });
    for (;;) {
      await new Promise(r => setTimeout(r, 2000));
      const st = await api("/api/refresh/status");
      if (st.running || st.scanning || st.finished_at === before) {
        const step = st.running ? (st.step || "Téléchargement") : "Analyse des produits";
        showStatus(`Mise à jour en cours (2 à 3 minutes) : ${step}… ${st.running ? `${st.done || 0}/${st.total || "?"}` : ""}`);
        continue;
      }
      showStatus(st.errors.length ? `Terminé avec ${st.errors.length} erreur(s) : ${st.errors.join(" · ")}` : "Données à jour.", st.errors.length > 0);
      if (!st.errors.length) setTimeout(() => showStatus(""), 3000);
      break;
    }
    route();
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
}
$("#refreshBtn").addEventListener("click", refreshData);

// ------------------------------------------------------------------ navigation
async function route() {
  const h = location.hash || "#/";
  const tab = h.startsWith("#/marches") ? "markets" : h.startsWith("#/reglages") ? "settings" : h.startsWith("#/actif/") ? "" : "home";
  document.querySelectorAll(".tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
  if (chart && !h.startsWith("#/actif/")) { chart.remove(); chart = null; }
  try {
    if (h.startsWith("#/actif/")) await renderAsset(decodeURIComponent(h.slice(8)));
    else if (tab === "markets") await renderMarkets();
    else if (tab === "settings") await renderSettings();
    else await renderHome();
  } catch (err) {
    view.innerHTML = `<div class="card empty">Erreur : ${esc(err.message)}<br><br>Le serveur Python est-il lancé ?</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
loadRegime();
route();
