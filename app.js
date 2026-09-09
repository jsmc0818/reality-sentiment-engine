/* Scheduled static evidence only. All valuation edits remain in memory. */
"use strict";
const M = typeof module !== "undefined" && module.exports ? require("./model.js") : window.ResearchModel;
const SYMBOLS = ["MSFT", "NVDA", "GOOGL", "AMZN", "META", "AAPL", "TSLA"];
const SCOPE_NAMES = {sp500: "S&P 500", ndx100: "Nasdaq-100", mag7: "Mag7 basket"};
const money = n => Number.isFinite(n) ? new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", maximumFractionDigits:2}).format(n) : "Unavailable";
const pct = (n, digits = 1) => Number.isFinite(n) ? `${n > 0 ? "+" : ""}${n.toFixed(digits)}%` : "Unavailable";
const billions = n => Number.isFinite(n) ? `$${(n / 1e9).toFixed(1)}B` : "Unavailable";
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sign = n => n >= 0 ? "positive" : "negative";
const moodLabel = n => n <= 30 ? "Selling pressure" : n >= 70 ? "Buying pressure" : "Balanced";
const badge = (label, tone = "neutral") => `<span class="badge ${tone}">${esc(label)}</span>`;
let data, selected = "MSFT", assumptions, filter = "all";

function validateStocks(payload) {
  if (!payload || payload.schema_version !== 1 || payload.methodology !== M.METHOD ||
      !Number.isFinite(Date.parse(payload.generated_at)) || !Array.isArray(payload.stocks) ||
      payload.stocks.map(s => s.symbol).join() !== SYMBOLS.join()) throw new Error("Invalid stock evidence");
  for (const s of payload.stocks) {
    if (!["available", "limited", "unavailable"].includes(s.status) || typeof s.collected_at !== "string") throw new Error("Invalid stock status");
    if (![s.name,s.sector,s.question,s.countercase,s.invalidation].every(x => typeof x === "string") ||
        !Array.isArray(s.drivers) || !s.drivers.every(x => typeof x === "string") ||
        !/^https:\/\//.test(s.ir) || s.collected_at !== payload.generated_at) throw new Error("Invalid stock metadata");
    if (s.market && (![s.market.price, s.market.mood].every(Number.isFinite) || s.market.price <= 0 || s.market.mood < 0 || s.market.mood > 100 || !Array.isArray(s.market.history))) throw new Error("Invalid market evidence");
    if (s.status === "available" && (!s.financials || !s.market || !Number.isFinite(s.market.market_cap))) throw new Error("Missing required stock evidence");
    if (s.financials && ![s.financials.revenue,s.financials.operating_margin_pct,s.financials.cash,s.financials.debt,s.financials.free_cash_flow,s.financials.operating_cash_flow].every(Number.isFinite)) throw new Error("Invalid financial evidence");
  }
  return payload;
}

function renderContext(payload) {
  const target = document.getElementById("market-context");
  if (!payload || !payload.scopes || M.marketAge(payload.asof) > 1) {
    target.innerHTML = `<p class="context-empty">Index observations are ${payload?.asof ? `dated ${esc(payload.asof)} and currently stale` : "unavailable"}. Live readings are withheld. Stock observations have independent timestamps.</p>`;
    return;
  }
  target.innerHTML = Object.entries(SCOPE_NAMES).map(([key, name]) => {
    const s = payload.scopes[key];
    if (!s || ![s.panic,s.fundamentals].every(Number.isFinite)) return `<p class="context-empty">${name}: unavailable</p>`;
    return `<article class="context-reading"><div class="context-name">${name}<span>${esc(payload.asof)}</span></div><div class="context-metrics"><div><strong>${s.panic.toFixed(0)}</strong><small>Panic / 100</small></div><div><strong>${s.fundamentals.toFixed(0)}</strong><small>Revisions / 100</small></div></div></article>`;
  }).join("");
}

function renderOverview() {
  const points = [], rows = [], signals = [];
  let ready = 0;
  for (const s of data.stocks) {
    const state = M.classify(s), e = M.evidence(s), r = M.resilience(s), m = s.market;
    const v = e.ready ? M.value(s, M.defaults(s)) : null;
    const color = r.code === "resilient" ? "green" : r.code === "weakening" ? "red" : "amber";
    signals.push(`<button type="button" class="signal-row ${s.symbol === selected ? "selected" : ""}" data-symbol="${s.symbol}" aria-label="${s.symbol}: ${esc(state.label)}. Open research."><i class="dot ${e.ready ? color : "amber"}" aria-hidden="true"></i><span><strong>${s.symbol}</strong><small>${esc(state.label)}</small></span><span class="signal-arrow" aria-hidden="true">↗</span></button>`);
    if (e.ready && v) {
      ready++;
      const x = m.mood, y = Math.max(0, Math.min(100, 50 - v.upside / 120 * 100));
      const lane = y > 88 ? -21 : y < 12 ? 21 : points.length % 2 === 0 ? -21 : 21;
      points.push(`<button type="button" class="map-point ${r.code} ${s.symbol === selected ? "selected" : ""}" style="left:clamp(14px,${x}%,calc(100% - 14px));top:clamp(14px,${y}%,calc(100% - 14px));--label-offset:${lane}px" data-symbol="${s.symbol}" aria-label="${s.symbol}: mood ${m.mood.toFixed(0)}, reference upside ${pct(v.upside)}, ${r.label}. Open research." title="${s.symbol} · ${pct(v.upside)} reference upside · mood ${m.mood.toFixed(0)}"><i aria-hidden="true"></i><span>${s.symbol}</span></button>`);
    }
    if (filter === "discount" && !["fear","fragile","discount"].includes(state.code)) continue;
    if (filter === "premium" && !["optimism","demanding"].includes(state.code)) continue;
    if (filter === "unclear" && state.code !== "unclear") continue;
    const priceFresh = m && M.marketAge(m.price_date) <= 1;
    rows.push(`<tr data-symbol="${s.symbol}" class="${s.symbol === selected ? "selected" : ""}"><td><div class="ticker-cell"><span class="ticker-icon">${s.symbol.slice(0,2)}</span><span><strong>${s.symbol}</strong><small>${esc(s.name)}</small></span></div></td><td class="price-cell"><strong>${priceFresh ? money(m.price) : "Withheld"}</strong><small class="${priceFresh ? sign(m.change_1d_pct) : "muted"}">${priceFresh ? pct(m.change_1d_pct) : esc(m?.price_date || "No quote")}</small></td><td>${priceFresh ? `<div class="mood-number"><strong>${m.mood.toFixed(0)}</strong>${moodLabel(m.mood)}</div><div class="mood-track"><i style="left:${m.mood}%"></i></div>` : "Unavailable"}</td><td>${badge(e.ready ? r.label : e.label,e.ready ? color : "neutral")}</td><td class="${v ? sign(v.upside) : "muted"}">${v ? pct(v.upside) : "Unclassified"}</td><td>${badge(state.label,state.tone)}</td><td><button type="button" class="row-open" data-symbol="${s.symbol}" aria-label="Open ${esc(s.name)} research">↗</button></td></tr>`);
  }
  document.getElementById("map-points").innerHTML = points.join("") || '<p class="map-empty">No fresh, complete stock evidence. Research framework remains available below.</p>';
  document.getElementById("map-coverage").textContent = `${ready}/7 positioned · Points beyond the scale are pinned to its edge.`;
  document.getElementById("watchlist-body").innerHTML = rows.join("") || '<tr><td colspan="7" class="empty-state">No stocks meet this filter.</td></tr>';
  document.getElementById("stock-tabs").innerHTML = data.stocks.map(s => `<button type="button" data-symbol="${s.symbol}" aria-pressed="${s.symbol === selected}">${s.symbol}</button>`).join("");
  document.getElementById("signal-status").innerHTML = signals.join("");
}

function sparkline(history) {
  if (!history?.length) return "";
  const values = history.map(p => p.close), low = Math.min(...values), high = Math.max(...values);
  const points = values.map((v, i) => `${i / Math.max(1,values.length-1) * 300},${46 - (v-low) / (high-low || 1) * 40}`).join(" ");
  return `<svg class="sparkline" viewBox="0 0 300 52" preserveAspectRatio="none" role="img" aria-label="Closing prices from ${esc(history[0].date)} to ${esc(history.at(-1).date)}"><polyline points="${points}" fill="none" stroke="${values.at(-1) >= values[0] ? "#50d8e9" : "#ffb689"}" stroke-width="1.7" vector-effect="non-scaling-stroke"/></svg>`;
}

function renderDetail() {
  const s = data.stocks.find(x => x.symbol === selected), e = M.evidence(s), r = M.resilience(s), state = M.classify(s);
  const m = s.market, f = s.financials, estimate = s.estimates;
  const priceFresh = m && M.marketAge(m.price_date) <= 1;
  document.title = `${s.symbol} Research | Reality Sentiment Engine`;
  const metric = (label, value, sub = "") => `<div><dt>${label}</dt><dd>${value}${sub ? `<small>${sub}</small>` : ""}</dd></div>`;
  document.getElementById("stock-detail").innerHTML = `<div class="company-head"><div><p class="eyebrow">${esc(s.sector)}</p><h3>${esc(s.name)}<span>${s.symbol} / USD</span></h3>${badge(e.label,e.ready ? "green" : "amber")}</div><div class="company-quote"><strong>${priceFresh ? money(m.price) : "Withheld"}</strong><small>${m ? `Close ${esc(m.price_date)}` : "No quote available"}</small></div></div>
    <div class="stock-summary"><div class="summary-cell"><p class="eyebrow">REFERENCE SETUP</p>${badge(state.label,state.tone)}<p>${state.detail}</p></div><div class="summary-cell"><p class="eyebrow">MARKET MOOD</p><h4>${priceFresh ? `${m.mood.toFixed(0)} / 100 · ${moodLabel(m.mood)}` : "Reading withheld"}</h4><p>${priceFresh ? `${pct(m.return_3m_pct)} over three months · ${pct(m.relative_return_3m_pts)} relative to SPY.` : "A fresh closing observation is required."}</p>${priceFresh ? sparkline(m.history) : ""}</div><div class="summary-cell"><p class="eyebrow">BUSINESS RESILIENCE</p><h4>${e.ready ? r.label : "Review dated evidence"}</h4><p>${r.detail}</p><p class="small">Historical financial screen. Competitive moat remains a research judgment.</p></div></div>
    <div class="evidence-grid"><section class="panel evidence-card"><p class="eyebrow">WHAT THE NUMBERS SAY</p><h3>Business evidence</h3>${f ? `<dl class="metric-grid">${metric("Revenue / trailing 12 months",billions(f.revenue))}${metric("Latest-quarter sales growth",pct(f.revenue_growth_yoy_pct),"Year over year")}${metric("Operating margin / TTM",`${f.operating_margin_pct.toFixed(1)}%`)}${metric("Latest-quarter margin change",Number.isFinite(f.margin_change_yoy_pts) ? `${f.margin_change_yoy_pts > 0 ? "+" : ""}${f.margin_change_yoy_pts.toFixed(1)} pts` : "Unavailable","Year over year")}${metric("Free cash flow / TTM",billions(f.free_cash_flow),"Operating cash flow less capex")}${metric("Net cash / (net debt)",billions(f.cash-f.debt))}${metric("Capital spending / TTM",billions(f.capex))}${metric("Stock compensation / TTM",billions(f.sbc),"Cash-flow dilution context")}${metric("Consensus EPS revision / 30D",pct(estimate?.revision_30d_pct),estimate ? `Fiscal target ${esc(estimate.target_end)}` : "No comparable estimate target")}</dl>` : '<p class="muted">Financial statements are incomplete. No resilience or valuation classification is published.</p>'}<p class="source-line">${f ? `TTM through ${esc(f.period_end)} · Balance sheet ${esc(f.balance_date)}<br>` : ""}Collected ${esc(s.collected_at.replace("T"," "))}<br><a href="https://finance.yahoo.com/quote/${s.symbol}/financials/" target="_blank" rel="noopener noreferrer">Financial statements ↗</a> · <a href="${esc(s.ir)}" target="_blank" rel="noopener noreferrer">Company disclosures ↗</a><br>Collection time is not the update time of each underlying analyst estimate.</p></section>
    <aside class="panel challenge-card"><p class="eyebrow">CHALLENGE YOUR CONVICTION</p><h3>${esc(s.question)}</h3><ul class="driver-list">${s.drivers.map(d => `<li>${esc(d)}</li>`).join("")}</ul><h4>Strongest counterargument to inspect</h4><p>${esc(s.countercase)}</p><h4>What would break the thesis?</h4><p>${esc(s.invalidation)}</p><p class="source-line">Standing research questions, not a claim about today's news or the cause of a price move.</p></aside></div>
    <section class="panel change-panel"><p class="eyebrow">WHAT CHANGED?</p><div><strong>${priceFresh ? pct(m.return_1w_pct) : "Withheld"}</strong><p>Price return over five sessions.</p></div><div>${s.previous_observation && f ? `<strong>${pct((f.revenue / s.previous_observation.revenue - 1)*100)}</strong><p>Change in reported TTM revenue versus the saved ${esc(s.previous_observation.date)} observation. Fiscal endpoint then: ${esc(s.previous_observation.period_end)}. This may reflect a new reporting period or a source revision.</p>` : '<strong>First observations</strong><p>Financial comparisons begin after a prior 7–14 day observation exists. No historical business evidence is reconstructed.</p>'}</div></section>`;
  assumptions = M.defaults(s);
  document.getElementById("lab").hidden = !assumptions || !e.ready;
  if (assumptions && e.ready) { renderControls(); renderValuation(); }
}

const CONTROLS = [
  ["growth","Revenue growth / 5Y",-10,60,.5,"%"], ["margin","Year-five operating margin",0,70,.5,"%"],
  ["discount","Discount rate / WACC",6,20,.25,"%"], ["terminal","Terminal growth",0,4,.25,"%"],
  ["capital","Sales-to-capital",.5,5,.1,"×"], ["tax","Normalized tax rate",0,40,1,"%"],
];

function renderControls() {
  document.getElementById("assumption-controls").innerHTML = CONTROLS.map(([key,label,min,max,step,unit]) => `<div class="control"><label for="input-${key}">${label}<output id="output-${key}" for="input-${key}">${assumptions[key].toFixed(unit === "×" ? 1 : 2)}${unit}</output></label><input type="range" id="input-${key}" data-assumption="${key}" min="${min}" max="${max}" step="${step}" value="${assumptions[key]}" aria-describedby="hint-${key}"><div class="bounds" id="hint-${key}"><span>${min}${unit}</span><span>${max}${unit}</span></div></div>`).join("");
}

function renderValuation() {
  const s = data.stocks.find(x => x.symbol === selected), results = M.scenarios(s,assumptions);
  const output = document.getElementById("valuation-output");
  if (!results?.base) { output.innerHTML = '<p class="error-note">Invalid assumptions. Discount rate must exceed terminal growth.</p>'; return; }
  const {bear,base,bull} = results, implied = M.impliedGrowth(s,assumptions);
  const roots = implied?.roots || [], growthText = roots.length === 1 ? `${roots[0].toFixed(1)}%` : roots.length > 1 ? "Multiple paths" : "Outside range";
  const growthDetail = roots.length === 1 ? `Five-year revenue CAGR that justifies today's price, holding your other assumptions fixed.` : roots.length > 1 ? `More than one growth rate clears today's price. Reinvestment makes the relationship non-monotonic.` : "No growth rate from −10% to 60% clears today's price under these margin and reinvestment assumptions.";
  const min = Math.min(bear.price,base.price,bull.price), max = Math.max(bear.price,base.price,bull.price);
  const marker = Math.max(0,Math.min(100,(s.market.price-min)/(max-min || 1)*100));
  const custom = CONTROLS.some(([key]) => Math.abs(assumptions[key]-M.defaults(s)[key]) > .001);
  document.getElementById("model-status").textContent = custom ? "YOUR SCENARIO" : "REFERENCE SCENARIO";
  const scenario = (label,v) => `<div><small>${label}</small><strong>${money(v.price)}</strong><span>${pct(v.upside)} vs close</span></div>`;
  output.innerHTML = `<div class="valuation-main"><div><p class="eyebrow">MODEL VALUE / SHARE</p><div class="valuation-number">${money(base.price)}</div><p class="valuation-caption"><span class="${sign(base.upside)}">${pct(base.upside)} versus ${money(s.market.price)}</span><br>Scenario output, not a price target.</p></div><div class="implied-box"><p class="eyebrow">GROWTH REQUIRED BY PRICE</p><div class="implied-number">${growthText}</div><p>${growthDetail}</p></div></div><div class="range-chart"><div class="scenario-grid">${scenario("Bear",bear)}${scenario(custom ? "Your case" : "Reference",base)}${scenario("Bull",bull)}</div><div class="range-line"><i style="left:${marker}%" aria-hidden="true"></i></div><p class="range-caption">White marker: current close ${money(s.market.price)}${s.market.price < min || s.market.price > max ? " (outside scenario range; pinned to edge)" : ""}. Range reflects assumptions, not statistical confidence.</p></div><p class="model-warning">${base.terminalShare !== null ? `${base.terminalShare.toFixed(0)}% of enterprise value comes from the terminal period. ` : "Terminal economics produce no positive enterprise value. "}Test reinvestment, taxes and discount rate before relying on the result. Defaults are mechanical, unreviewed assumptions.</p>`;
  document.getElementById("cashflow-table").innerHTML = `<table class="comparison-table"><caption class="sr-only">Five-year forecast in billions of US dollars</caption><thead><tr><th>Year</th><th>Revenue</th><th>Margin</th><th>Reinvestment</th><th>FCFF</th></tr></thead><tbody>${base.flows.map(f => `<tr><td>${f.year}</td><td>${billions(f.revenue)}</td><td>${(f.margin*100).toFixed(1)}%</td><td>${billions(f.reinvestment)}</td><td>${billions(f.fcff)}</td></tr>`).join("")}</tbody></table>`;
}

function selectStock(symbol, scroll = false) {
  if (!SYMBOLS.includes(symbol) || !data) return;
  selected = symbol;
  history.replaceState(null,"",`#stock=${symbol}`);
  renderOverview(); renderDetail();
  if (scroll) setNavigation("#research");
  if (scroll) document.getElementById("research").scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}

function setNavigation(hash) {
  document.querySelectorAll('.site-header nav a').forEach(link => {
    const active = link.getAttribute("href") === hash;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}

async function init() {
  document.getElementById("state-filter").addEventListener("change",e => { filter=e.target.value; if (data) renderOverview(); });
  document.addEventListener("click",e => {
    const button=e.target.closest("[data-symbol]");
    if (button) selectStock(button.dataset.symbol,!button.closest("#stock-tabs"));
    const link=e.target.closest('a[href^="#"]');
    if (link) {
      let hash=link.getAttribute("href");
      if (hash === "#lab" && document.getElementById("lab").hidden) {
        e.preventDefault();
        hash="#research";
        document.getElementById("research").scrollIntoView();
        history.replaceState(null,"",hash);
      }
      setNavigation(hash);
    }
  });
  document.getElementById("assumption-controls").addEventListener("input",e => {
    const key=e.target.dataset.assumption;
    if (!CONTROLS.some(c=>c[0]===key)) return;
    assumptions[key]=Number(e.target.value);
    const unit=CONTROLS.find(c=>c[0]===key)[5];
    document.getElementById(`output-${key}`).textContent=`${assumptions[key].toFixed(unit === "×" ? 1 : 2)}${unit}`;
    renderValuation();
  });
  document.getElementById("reset-model").addEventListener("click",()=>{if(data) {assumptions=M.defaults(data.stocks.find(s=>s.symbol===selected));renderControls();renderValuation();}});
  const fetchJSON=async url=>{const response=await fetch(url,{cache:"no-cache"});if(!response.ok)throw new Error("Publication unavailable");return response.json();};
  const [stocks,context]=await Promise.allSettled([fetchJSON("data/stocks.json"),fetchJSON("data/scores.json")]);
  renderContext(context.status === "fulfilled" ? context.value : null);
  try {
    if(stocks.status !== "fulfilled") throw new Error("Stock publication unavailable");
    data=validateStocks(stocks.value);
    const fromHash=location.hash.match(/^#stock=([A-Z]+)$/)?.[1];
    if(SYMBOLS.includes(fromHash)) selected=fromHash;
    document.getElementById("publication").textContent=`Stock evidence collected ${data.generated_at.slice(0,10)} · after US close`;
    const stale=data.stocks.filter(s=>!M.evidence(s).ready).length;
    if(stale) document.getElementById("load-status").innerHTML=`<p class="error-note">${stale} of 7 companies have stale or incomplete evidence. Their classifications are withheld; dated financial observations remain inspectable.</p>`;
    renderOverview();renderDetail();
    if (location.hash) setNavigation(location.hash.startsWith("#stock=") ? "#research" : location.hash);
  } catch {
    document.getElementById("load-status").innerHTML='<p class="error-note">Stock evidence is unavailable or failed validation. No substitute scores are shown. Please return after the next successful scheduled publication.</p>';
    document.getElementById("map-points").innerHTML='<p class="map-empty">Stock classifications unavailable.</p>';
    document.getElementById("watchlist-body").innerHTML='<tr><td colspan="7" class="empty-state">No validated stock publication.</td></tr>';
    document.getElementById("stock-detail").innerHTML='<p class="muted">Research calculations require a validated stock publication. Read the methodology below.</p>';
    document.getElementById("signal-status").innerHTML='<p class="context-empty">Company signals unavailable. No validated publication.</p>';
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports={validateStocks};
  if(require.main===module) {
    const fs=require("node:fs");
    const stocks=validateStocks(JSON.parse(fs.readFileSync(require("node:path").join(__dirname,"data/stocks.json"),"utf8")));
    for(const s of stocks.stocks) if(s.status === "available" && M.defaults(s) && !M.value(s,M.defaults(s))) throw new Error(`Invalid model for ${s.symbol}`);
    console.log("Stock dashboard bindings and reference valuations validated");
  }
} else init();
