const SCOPE_NAMES = {
  sp500: "S&P 500",
  ndx100: "Nasdaq 100",
  mag7: "Magnificent Seven",
};

const SCOPE_COLORS = {
  sp500: "#68dcff",
  ndx100: "#ff9e4f",
  mag7: "#ed86bd",
};

const LABEL_OFFSETS = { sp500: -5, ndx100: -6, mag7: 5 };

const PANIC_WEIGHTS = {
  sp500: { term_structure: 25, credit_velocity: 22, vvix: 20, breadth: 18, put_call: 15 },
  ndx100: { vxn_ratio: 25, vxn_level: 20, credit_velocity: 22, breadth: 18, put_call: 15 },
  mag7: { vxn_ratio: 25, vxn_level: 20, credit_velocity: 22, pairwise_corr: 18, put_call: 15 },
};

const FUNDAMENTALS_WEIGHTS = { revision_score: 60, revision_breadth: 40 };
const ENTRY_ORDER = ["forward_pe", "equity_risk_premium_pts", "trailing_pe", "divergence_pts"];
const QUADRANT_LABELS = {
  normal: "Normal",
  golden: "Candidate Dislocation",
  watch: "Watch",
  trap: "Complacency Trap",
  fire: "Real Fire",
};
const QUADRANT_COLORS = {
  normal: "#669741",
  golden: "#b66a18",
  watch: "#7463b6",
  trap: "#397d9a",
  fire: "#c44831",
};

const COMPONENTS = {
  term_structure: ["VIX Term Structure", "Short-term VIX compared with three-month VIX. A deep, lasting inversion means investors want protection now.", "Cboe", "https://www.cboe.com/tradable-products/vix/term-structure"],
  credit_velocity: ["Credit Spread Velocity", "How quickly high-yield borrowing costs changed over ten days. Fast widening means stress is spreading into credit.", "FRED HY OAS", "https://fred.stlouisfed.org/series/BAMLH0A0HYM2"],
  vvix: ["VVIX", "The volatility of VIX itself. A high percentile means protection prices are becoming unstable.", "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVVIX/"],
  breadth: ["Breadth Washout", "The share of companies above their 200-day average, scored in reverse. Fewer survivors means broader selling.", "Yahoo constituent prices", "https://finance.yahoo.com/"],
  put_call: ["Equity Put/Call", "Put volume compared with call volume. More puts usually mean more demand for downside protection.", "Cboe", "https://www.cboe.com/us/options/market_statistics/daily/"],
  vxn_ratio: ["VXN / VIX", "Nasdaq volatility compared with broad-market volatility. A high score means fear is concentrated in growth and technology.", "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVXN/"],
  vxn_level: ["VXN Level", "The Nasdaq-100 implied-volatility percentile. Higher means near-term protection is more expensive.", "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVXN/"],
  pairwise_corr: ["Pairwise Correlation", "How closely the seven stocks move together over 20 days. High correlation can mean investors are selling the basket, not choosing stocks.", "Yahoo constituent prices", "https://finance.yahoo.com/"],
  revision_score: ["EPS Revision Momentum", "Combines 30D, 60D, and 90D next-year EPS revisions at 50%, 30%, and 20%. Changes inside ±0.25% are neutral.", "Yahoo analyst trends", "https://finance.yahoo.com/"],
  revision_breadth: ["Revision Breadth", "The covered proxy weight receiving upgrades, neutral revisions, or downgrades. Neutral revisions receive half credit so tiny changes cannot flip the score.", "Yahoo analyst trends", "https://finance.yahoo.com/"],
  forward_pe: ["Forward P/E", "The price paid for the sampled index's next-year earnings. It is valuation context, not a judgment on business health.", "Yahoo estimates", "https://finance.yahoo.com/"],
  trailing_pe: ["Trailing P/E", "The price paid for the sampled index's last twelve months of earnings. Compare it with forward P/E to understand embedded growth expectations.", "Yahoo estimates", "https://finance.yahoo.com/"],
  equity_risk_premium_pts: ["Equity Risk Premium", "Forward earnings yield less the 10-year Treasury yield. A thin or negative premium means healthy earnings expectations may already be expensive.", "Yahoo + FRED", "https://fred.stlouisfed.org/series/DGS10"],
  divergence_pts: ["EPS-Price Divergence", "Three-month EPS revision minus the three-month price return. Positive means price stress has outrun estimate damage.", "Yahoo estimates and prices", "https://finance.yahoo.com/"],
};

let payload;
let selected = "sp500";
let revealObserver;

function visualCoordinate(panic, fundamentals) {
  const u = panic <= 75 ? (panic / 75) * 0.5 : 0.5 + ((panic - 75) / 25) * 0.5;
  const v = 1 - fundamentals / 100;
  const topLeft = { x: 23.5, y: 13.5 };
  const topRight = { x: 77.1, y: 13.6 };
  const bottomLeft = { x: 7.5, y: 87.7 };
  const bottomRight = { x: 92.9, y: 87.7 };
  const left = { x: topLeft.x + (bottomLeft.x - topLeft.x) * v, y: topLeft.y + (bottomLeft.y - topLeft.y) * v };
  const right = { x: topRight.x + (bottomRight.x - topRight.x) * v, y: topRight.y + (bottomRight.y - topRight.y) * v };
  return { x: left.x + (right.x - left.x) * u, y: left.y + (right.y - left.y) * u };
}

function indicatorBand(score, group, key = "") {
  if (group === "panic") {
    const band = score >= 67 ? "high" : score >= 34 ? "mid" : "low";
    return [`${band} pressure`, band];
  }
  if (group === "fundamentals") {
    if (score >= 60) return ["healthy evidence", "high"];
    if (score > 40) return ["mixed evidence", "mid"];
    return ["deteriorating", "low"];
  }
  if (key === "equity_risk_premium_pts") {
    if (score > 2) return ["supportive premium", "high"];
    if (score >= 0) return ["thin premium", "mid"];
    return ["negative premium", "low"];
  }
  if (key === "divergence_pts") {
    if (score > 0) return ["price leads down", "high"];
    if (score >= -2) return ["roughly aligned", "mid"];
    return ["price leads up", "low"];
  }
  return ["valuation context", "context"];
}

function validatePayload(data) {
  if (!data || !data.scopes) throw new Error("Missing market scopes");
  Object.keys(SCOPE_NAMES).forEach((scope) => {
    const reading = data.scopes[scope];
    if (!reading || ![reading.panic, reading.fundamentals, reading.fundamental_discrepancy].every(Number.isFinite)) {
      throw new Error(`Invalid ${scope} headline reading`);
    }
    const coverage = reading.coverage;
    const eps = reading.analyst_eps;
    if (coverage?.fundamentals_ready !== true || ("panic_ready" in coverage && coverage.panic_ready !== true) || ![
      coverage.fundamentals_pct,
      coverage.entry_history_snapshot_count,
      coverage.entry_history_snapshot_minimum,
      eps?.analyst_eps_revision_30d_pct,
      eps?.analyst_eps_up_breadth_30d_pct,
    ].every(Number.isFinite) || ![
      eps?.analyst_eps_revision_60d_pct,
      eps?.analyst_eps_revision_90d_pct,
    ].some(Number.isFinite)) {
      throw new Error(`Invalid ${scope} supporting evidence`);
    }
    if (!reading.components?.panic || !reading.components?.fundamentals || !reading.components?.entry) {
      throw new Error(`Invalid ${scope} component groups`);
    }
  });
  return data;
}

function validateTimeline(data) {
  if (!data || data.schema_version !== 1 || !data.scopes) throw new Error("Invalid timeline contract");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(data.methodology_start)
      || !Number.isFinite(Date.parse(`${data.methodology_start}T00:00:00Z`))
      || typeof data.generated_at_utc !== "string"
      || !Number.isFinite(Date.parse(data.generated_at_utc))) {
    throw new Error("Invalid timeline metadata");
  }
  Object.keys(SCOPE_NAMES).forEach((scope) => {
    const points = data.scopes[scope];
    if (!Array.isArray(points)) throw new Error(`Missing ${scope} timeline`);
    let previous = "";
    points.forEach((point) => {
      if (!point || !/^\d{4}-\d{2}-\d{2}$/.test(point.date)
          || !Number.isFinite(Date.parse(`${point.date}T00:00:00Z`))
          || point.date <= previous) {
        throw new Error(`Invalid ${scope} timeline order`);
      }
      if (![point.panic, point.fundamentals, point.fundamental_discrepancy].every(Number.isFinite)
          || point.panic < 0 || point.panic > 100
          || point.fundamentals < 0 || point.fundamentals > 100
          || point.fundamental_discrepancy < -100 || point.fundamental_discrepancy > 100) {
        throw new Error(`Invalid ${scope} timeline point`);
      }
      previous = point.date;
    });
  });
  return data;
}

function publicLanguage(text) {
  return String(text || "")
    .replace(/Golden Zone/gi, "Candidate Dislocation")
    .replace(/Fundamental Discrepancy/gi, "Dislocation Gap")
    .replace(/Fundamentals Meter/gi, "Consensus Earnings Health")
    .replace(/Fundamentals/gi, "Consensus Earnings Health");
}

function formatValue(key, value, group) {
  if (group !== "entry") return value.toFixed(1);
  if (key === "forward_pe" || key === "trailing_pe") return `${value.toFixed(1)}×`;
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)} pts`;
}

function renderPoints() {
  const container = document.getElementById("map-points");
  container.replaceChildren();
  Object.entries(payload.scopes).forEach(([scope, reading]) => {
    const position = visualCoordinate(reading.panic, reading.fundamentals);
    const point = document.createElement("button");
    point.type = "button";
    point.className = "market-point";
    point.style.left = `${position.x}%`;
    point.style.top = `${position.y}%`;
    point.style.setProperty("--point-color", SCOPE_COLORS[scope]);
    point.dataset.scope = scope;
    point.setAttribute("aria-label", `${SCOPE_NAMES[scope]}: Panic ${reading.panic}, Consensus Earnings Health ${reading.fundamentals}`);
    point.addEventListener("click", () => selectScope(scope));

    const label = document.createElement("span");
    label.className = "point-label";
    label.style.left = `${position.x}%`;
    label.style.top = `${Math.max(8, position.y + LABEL_OFFSETS[scope])}%`;
    label.textContent = `${SCOPE_NAMES[scope]}  ${Math.round(reading.panic)} / ${Math.round(reading.fundamentals)}`;
    container.append(point, label);
  });
}

function componentCard(scope, key, score, group, index) {
  const [name, logic, source, url] = COMPONENTS[key];
  const [bandLabel, band] = indicatorBand(score, group, key);
  const shell = document.createElement("div");
  shell.className = "component-shell reveal";
  shell.style.setProperty("--index", index);

  const article = document.createElement("article");
  article.className = `component ${group} band-${band}`;
  const top = document.createElement("div");
  top.className = "component-top";
  const badge = document.createElement("span");
  badge.className = "component-badge";
  badge.textContent = bandLabel;
  const value = document.createElement("strong");
  value.className = "component-score";
  value.textContent = formatValue(key, score, group);
  top.append(badge, value);

  const heading = document.createElement("h4");
  heading.textContent = name;
  const measure = document.createElement("div");
  if (group === "entry") {
    measure.className = "entry-context";
    measure.textContent = "EXCLUDED FROM CONSENSUS EARNINGS HEALTH";
  } else {
    measure.className = "component-bar";
    const fill = document.createElement("span");
    fill.style.transform = `scaleX(${Math.max(0, Math.min(100, score)) / 100})`;
    measure.append(fill);
  }

  const description = document.createElement("p");
  description.textContent = logic;
  const detail = document.createElement("div");
  detail.className = "component-meta";
  const sourceLink = document.createElement("a");
  sourceLink.href = url;
  sourceLink.target = "_blank";
  sourceLink.rel = "noreferrer";
  sourceLink.textContent = source;
  const weightLabel = document.createElement("span");
  const weight = group === "panic" ? PANIC_WEIGHTS[scope][key] : FUNDAMENTALS_WEIGHTS[key];
  weightLabel.textContent = group === "entry" ? "Entry context only" : `${weight}% weight`;
  detail.append(sourceLink, weightLabel);
  article.append(top, heading, measure, description, detail);
  shell.append(article);
  return shell;
}

function renderComponents(scope, reading) {
  const panic = Object.entries(reading.components.panic).map(([key, score], index) => componentCard(scope, key, score, "panic", index));
  const fundamentals = Object.entries(reading.components.fundamentals).map(([key, score], index) => componentCard(scope, key, score, "fundamentals", index));
  const entry = ENTRY_ORDER.filter((key) => key in reading.components.entry).map((key, index) => componentCard(scope, key, reading.components.entry[key], "entry", index));
  document.getElementById("panic-components").replaceChildren(...panic);
  document.getElementById("fundamentals-components").replaceChildren(...fundamentals);
  document.getElementById("entry-components").replaceChildren(...entry);
}

function renderEvidence(reading) {
  const evidence = document.getElementById("evidence-strip");
  const eps = reading.analyst_eps;
  const longHorizon = Number.isFinite(eps.analyst_eps_revision_90d_pct) ? 90 : 60;
  const longRevision = eps[`analyst_eps_revision_${longHorizon}d_pct`];
  const values = [
    ["30D EPS", `${eps.analyst_eps_revision_30d_pct >= 0 ? "+" : ""}${eps.analyst_eps_revision_30d_pct.toFixed(2)}%`],
    [`${longHorizon}D EPS`, `${longRevision >= 0 ? "+" : ""}${longRevision.toFixed(2)}%`],
    ["Upgrade breadth", `${eps.analyst_eps_up_breadth_30d_pct.toFixed(1)}%`],
  ];
  evidence.replaceChildren(...values.map(([label, value]) => {
    const item = document.createElement("span");
    item.textContent = `${label} ${value}`;
    return item;
  }));
}

function selectScope(scope) {
  selected = scope;
  const reading = payload.scopes[scope];
  document.querySelectorAll(".scope-tab, .market-point").forEach((element) => element.setAttribute("aria-pressed", String(element.dataset.scope === scope)));
  const discrepancy = `${reading.fundamental_discrepancy >= 0 ? "+" : ""}${reading.fundamental_discrepancy.toFixed(1)}`;
  document.getElementById("selected-reading").textContent = `${SCOPE_NAMES[scope]} · Panic ${reading.panic.toFixed(1)} · Consensus Earnings Health ${reading.fundamentals.toFixed(1)} · Dislocation Gap ${discrepancy}`;
  document.querySelectorAll(".verdict-card").forEach((card) => card.classList.toggle("is-current", card.dataset.quadrant === reading.quadrant.code));
  const currentVerdict = document.getElementById("current-verdict");
  currentVerdict.style.setProperty("--current-color", QUADRANT_COLORS[reading.quadrant.code] || QUADRANT_COLORS.normal);
  document.getElementById("current-verdict-state").textContent = `${SCOPE_NAMES[scope]} · ${QUADRANT_LABELS[reading.quadrant.code] || publicLanguage(reading.quadrant.label)}`;
  document.getElementById("current-verdict-copy").textContent = publicLanguage(reading.verdict);
  const coverage = reading.coverage;
  const entryStatus = coverage.entry_history_snapshot_count >= coverage.entry_history_snapshot_minimum
    ? "Three-month entry divergence is available."
    : `Entry divergence is building: ${coverage.entry_history_snapshot_count}/${coverage.entry_history_snapshot_minimum} comparable daily endpoints.`;
  const commonWeight = Number.isFinite(coverage.fundamentals_common_weight_pct)
    ? ` · ${coverage.fundamentals_common_weight_pct}% common-horizon proxy weight.`
    : "";
  const panicDate = coverage.panic_asof ? ` Panic inputs as of ${coverage.panic_asof}.` : "";
  document.getElementById("warmup").textContent = `Consensus Earnings Health ready · ${coverage.fundamentals_pct}% market-cap-proxy coverage.${commonWeight}${panicDate} ${entryStatus}`;
  renderEvidence(reading);
  renderComponents(scope, reading);
  observeReveals();
}

function observeReveals() {
  const elements = document.querySelectorAll(".reveal:not([data-observed])");
  if (!("IntersectionObserver" in window)) {
    elements.forEach((element) => element.classList.add("is-visible"));
    return;
  }
  revealObserver ||= new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  elements.forEach((element) => {
    element.dataset.observed = "true";
    revealObserver.observe(element);
  });
}

function render() {
  const generated = new Date(payload.generated_at_utc);
  document.getElementById("asof").textContent = `Data as of ${payload.asof} · Updated ${generated.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}`;
  document.getElementById("scope-tabs").replaceChildren(...Object.keys(payload.scopes).map((scope) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scope-tab";
    button.dataset.scope = scope;
    button.style.setProperty("--scope-color", SCOPE_COLORS[scope]);
    button.textContent = SCOPE_NAMES[scope];
    button.addEventListener("click", () => selectScope(scope));
    return button;
  }));
  renderPoints();
  selectScope(selected);
}

if (typeof document !== "undefined") {
  const loadJson = (url) => fetch(url, { cache: "no-store" }).then((response) => {
    if (!response.ok) throw new Error(`${url} unavailable`);
    return response.json();
  });
  loadJson("data/scores.json")
    .then((scores) => {
      payload = validatePayload(scores);
      render();
    })
    .catch(() => {
      document.getElementById("asof").textContent = "Market data is temporarily unavailable";
      document.getElementById("warmup").textContent = "The latest reading did not pass the public data contract.";
      observeReveals();
    });
}

if (typeof module !== "undefined") {
  module.exports = { indicatorBand, publicLanguage, validatePayload, validateTimeline, visualCoordinate };
  if (require.main === module) {
    const fs = require("node:fs");
    const data = JSON.parse(fs.readFileSync("data/scores.json", "utf8"));
    validatePayload(data);
    if (fs.existsSync("data/timeline.json")) validateTimeline(JSON.parse(fs.readFileSync("data/timeline.json", "utf8")));
    console.assert(indicatorBand(80, "panic")[0] === "high pressure");
    console.assert(indicatorBand(50, "fundamentals")[0] === "mixed evidence");
    console.assert(visualCoordinate(80, 80).y < visualCoordinate(80, 30).y);
    console.assert(publicLanguage("Golden Zone / Fundamentals") === "Candidate Dislocation / Consensus Earnings Health");
  }
}
