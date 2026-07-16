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
const TIMELINE_SERIES = {
  panic: { key: "panic", label: "Panic", color: "#b66a18", scale: "score" },
  fundamentals: { key: "fundamentals", label: "Consensus Earnings Health", color: "#397a64", scale: "score" },
  gap: { key: "fundamental_discrepancy", label: "Dislocation Gap", color: "#7463b6", scale: "gap" },
};
const TIMELINE_MONTHS = { "1M": 1, "3M": 3, "1Y": 12 };
const CHART = { width: 1200, height: 500, left: 72, right: 78, top: 36, bottom: 62 };
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
let timelinePayload;
let selected = "sp500";
let selectedRange = "1Y";
const selectedTimelineSeries = new Set(["panic", "fundamentals"]);
let visibleTimelinePoints = [];
let timelineFocusIndex = -1;
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

function timelineRange(points, range) {
  if (!points.length || range === "All") return points.slice();
  const cutoff = new Date(`${points.at(-1).date}T00:00:00Z`);
  const day = cutoff.getUTCDate();
  cutoff.setUTCDate(1);
  cutoff.setUTCMonth(cutoff.getUTCMonth() - TIMELINE_MONTHS[range]);
  const lastDay = new Date(Date.UTC(cutoff.getUTCFullYear(), cutoff.getUTCMonth() + 1, 0)).getUTCDate();
  cutoff.setUTCDate(Math.min(day, lastDay));
  return points.filter((point) => new Date(`${point.date}T00:00:00Z`) >= cutoff);
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

function timelineDate(date, compact = false) {
  const value = new Date(`${date}T00:00:00Z`);
  return value.toLocaleDateString([], compact
    ? { month: "short", day: "numeric", timeZone: "UTC" }
    : { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

function timelineX(point) {
  const plotWidth = CHART.width - CHART.left - CHART.right;
  if (visibleTimelinePoints.length < 2) return CHART.left + plotWidth / 2;
  const start = Date.parse(`${visibleTimelinePoints[0].date}T00:00:00Z`);
  const end = Date.parse(`${visibleTimelinePoints.at(-1).date}T00:00:00Z`);
  return CHART.left + ((Date.parse(`${point.date}T00:00:00Z`) - start) / (end - start)) * plotWidth;
}

function timelineY(value, scale) {
  const plotHeight = CHART.height - CHART.top - CHART.bottom;
  const normalized = scale === "gap" ? (value + 100) / 200 : value / 100;
  return CHART.top + (1 - normalized) * plotHeight;
}

function timelinePath(points, series) {
  return points.map((point, index) => `${index ? "L" : "M"}${timelineX(point).toFixed(2)},${timelineY(point[series.key], series.scale).toFixed(2)}`).join(" ");
}

function renderTimelineLatest(points) {
  const latestBox = document.getElementById("timeline-latest");
  latestBox.replaceChildren();
  const scope = document.createElement("span");
  scope.textContent = SCOPE_NAMES[selected];
  const latest = points.at(-1);
  if (!latest) {
    const message = document.createElement("strong");
    message.textContent = "No validated history yet";
    latestBox.append(scope, message);
    return;
  }
  const date = document.createElement("strong");
  date.textContent = timelineDate(latest.date);
  const values = document.createElement("small");
  values.textContent = `Panic ${latest.panic.toFixed(1)} · Earnings Health ${latest.fundamentals.toFixed(1)} · Gap ${latest.fundamental_discrepancy >= 0 ? "+" : ""}${latest.fundamental_discrepancy.toFixed(1)}`;
  latestBox.append(scope, date, values);
}

function showTimelinePoint(index) {
  if (!visibleTimelinePoints.length) return;
  timelineFocusIndex = Math.max(0, Math.min(index, visibleTimelinePoints.length - 1));
  const point = visibleTimelinePoints[timelineFocusIndex];
  const x = timelineX(point);
  const cursor = document.getElementById("timeline-cursor");
  const tooltip = document.getElementById("timeline-tooltip");
  if (!cursor || !tooltip) return;

  cursor.removeAttribute("hidden");
  cursor.innerHTML = `<line class="timeline-cursor-line" x1="${x}" y1="${CHART.top}" x2="${x}" y2="${CHART.height - CHART.bottom}"></line>`;
  selectedTimelineSeries.forEach((seriesName) => {
    const series = TIMELINE_SERIES[seriesName];
    cursor.insertAdjacentHTML("beforeend", `<circle class="timeline-cursor-dot" cx="${x}" cy="${timelineY(point[series.key], series.scale)}" r="6" fill="${series.color}"></circle>`);
  });

  const date = document.createElement("time");
  date.dateTime = point.date;
  date.textContent = timelineDate(point.date);
  const rows = [...selectedTimelineSeries].map((seriesName) => {
    const series = TIMELINE_SERIES[seriesName];
    const row = document.createElement("span");
    const label = document.createElement("i");
    label.style.setProperty("--series-color", series.color);
    label.textContent = series.label;
    const value = document.createElement("strong");
    const number = point[series.key];
    value.textContent = `${series.scale === "gap" && number >= 0 ? "+" : ""}${number.toFixed(1)}`;
    row.append(label, value);
    return row;
  });
  tooltip.replaceChildren(date, ...rows);
  tooltip.classList.add("is-visible");
  const chart = document.getElementById("timeline-chart");
  tooltip.style.left = `${chart.offsetLeft + (x / CHART.width) * chart.clientWidth}px`;
  tooltip.dataset.align = x < CHART.width * .25 ? "left" : x > CHART.width * .75 ? "right" : "center";
}

function hideTimelinePoint() {
  document.getElementById("timeline-cursor")?.setAttribute("hidden", "");
  document.getElementById("timeline-tooltip")?.classList.remove("is-visible");
}

function renderTimeline() {
  if (!timelinePayload) return;
  const allPoints = timelinePayload.scopes[selected];
  visibleTimelinePoints = timelineRange(allPoints, selectedRange);
  timelineFocusIndex = visibleTimelinePoints.length - 1;
  renderTimelineLatest(allPoints);

  const svg = document.getElementById("timeline-chart");
  const state = document.getElementById("timeline-state");
  const activeSeries = [...selectedTimelineSeries];
  const methodology = timelineDate(timelinePayload.methodology_start);
  const generated = new Date(timelinePayload.generated_at_utc).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  document.getElementById("timeline-methodology").textContent = `Methodology start ${methodology} · ${allPoints.length} validated daily ${allPoints.length === 1 ? "snapshot" : "snapshots"} · Updated ${generated}`;

  state.className = "timeline-state";
  state.textContent = "";
  svg.removeAttribute("hidden");
  if (!activeSeries.length) {
    svg.setAttribute("hidden", "");
    state.textContent = "Choose at least one series to draw the timeline.";
    state.classList.add("is-visible");
    return;
  }
  if (!visibleTimelinePoints.length) {
    svg.setAttribute("hidden", "");
    state.textContent = allPoints.length ? "No validated snapshots fall inside this range. Choose All to see the available history." : "No validated timeline snapshots are available yet. The chart will begin with the first successful daily publication.";
    state.classList.add("is-visible");
    return;
  }
  if (visibleTimelinePoints.length === 1) {
    state.textContent = "One validated snapshot is available. A trend line will appear after the next successful daily publication.";
    state.classList.add("is-visible", "is-note");
  }

  const hasScore = activeSeries.some((name) => TIMELINE_SERIES[name].scale === "score");
  const hasGap = activeSeries.includes("gap");
  const axisValues = hasScore ? [0, 25, 50, 75, 100] : [-100, -50, 0, 50, 100];
  const axisScale = hasScore ? "score" : "gap";
  const plotRight = CHART.width - CHART.right;
  const plotBottom = CHART.height - CHART.bottom;
  const grid = axisValues.map((value) => {
    const y = timelineY(value, axisScale);
    return `<line class="timeline-grid" x1="${CHART.left}" y1="${y}" x2="${plotRight}" y2="${y}"></line><text class="timeline-axis-label" x="${CHART.left - 14}" y="${y + 5}" text-anchor="end">${value}</text>`;
  }).join("");
  const rightAxis = hasGap && hasScore ? [100, 50, 0, -50, -100].map((value, index) => {
    const y = timelineY([100, 75, 50, 25, 0][index], "score");
    return `<text class="timeline-axis-label gap-axis-label" x="${plotRight + 15}" y="${y + 5}">${value}</text>`;
  }).join("") : "";

  const tickCount = Math.min(5, visibleTimelinePoints.length);
  const tickIndexes = tickCount === 1 ? [0] : [...new Set(Array.from({ length: tickCount }, (_, index) => Math.round(index * (visibleTimelinePoints.length - 1) / (tickCount - 1))))];
  const xTicks = tickIndexes.map((index) => {
    const point = visibleTimelinePoints[index];
    const x = timelineX(point);
    return `<line class="timeline-x-tick" x1="${x}" y1="${plotBottom}" x2="${x}" y2="${plotBottom + 8}"></line><text class="timeline-date-label" x="${x}" y="${plotBottom + 34}" text-anchor="middle">${timelineDate(point.date, true)}</text>`;
  }).join("");

  const thresholds = [
    selectedTimelineSeries.has("panic") && [75, "score", "panic", "High panic 75"],
    selectedTimelineSeries.has("fundamentals") && [60, "score", "healthy", "Healthy earnings 60"],
    selectedTimelineSeries.has("fundamentals") && [40, "score", "broken", "Breaking earnings 40"],
    selectedTimelineSeries.has("gap") && [0, "gap", "gap", "Gap baseline 0"],
  ].filter(Boolean).map(([value, scale, className, label]) => {
    const y = timelineY(value, scale);
    return `<line class="timeline-threshold ${className}" x1="${CHART.left}" y1="${y}" x2="${plotRight}" y2="${y}"></line><text class="timeline-threshold-label ${className}" x="${CHART.left + 10}" y="${y - 7}">${label}</text>`;
  }).join("");

  const lines = activeSeries.map((seriesName) => {
    const series = TIMELINE_SERIES[seriesName];
    const latest = visibleTimelinePoints.at(-1);
    const path = visibleTimelinePoints.length > 1
      ? `<path class="timeline-line" d="${timelinePath(visibleTimelinePoints, series)}" stroke="${series.color}"></path>`
      : "";
    return `${path}<circle class="timeline-endpoint" cx="${timelineX(latest)}" cy="${timelineY(latest[series.key], series.scale)}" r="5" fill="${series.color}"></circle>`;
  }).join("");

  svg.innerHTML = `
    <title id="timeline-chart-title">${SCOPE_NAMES[selected]} sentiment indicator history</title>
    <desc id="timeline-chart-desc">${visibleTimelinePoints.length} validated daily snapshots. Focus the chart and use the left and right arrow keys to inspect readings.</desc>
    <rect class="timeline-plot" x="${CHART.left}" y="${CHART.top}" width="${plotRight - CHART.left}" height="${plotBottom - CHART.top}"></rect>
    ${grid}${rightAxis}${thresholds}${xTicks}${lines}
    <g id="timeline-cursor" hidden></g>
    <rect class="timeline-hit-area" x="${CHART.left}" y="${CHART.top}" width="${plotRight - CHART.left}" height="${plotBottom - CHART.top}"></rect>`;
  const shell = document.getElementById("timeline-chart-shell");
  requestAnimationFrame(() => {
    const latestX = (timelineX(visibleTimelinePoints.at(-1)) / CHART.width) * svg.clientWidth;
    shell.scrollLeft = Math.max(0, latestX - shell.clientWidth / 2);
  });
  if (document.activeElement === svg) showTimelinePoint(timelineFocusIndex);
}

function bindTimelineControls() {
  document.querySelectorAll("[data-series]").forEach((button) => button.addEventListener("click", () => {
    const series = button.dataset.series;
    selectedTimelineSeries.has(series) ? selectedTimelineSeries.delete(series) : selectedTimelineSeries.add(series);
    button.setAttribute("aria-pressed", String(selectedTimelineSeries.has(series)));
    hideTimelinePoint();
    renderTimeline();
  }));
  document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
    selectedRange = button.dataset.range;
    document.querySelectorAll("[data-range]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    hideTimelinePoint();
    renderTimeline();
  }));

  const svg = document.getElementById("timeline-chart");
  svg.addEventListener("pointermove", (event) => {
    if (!visibleTimelinePoints.length) return;
    const rect = svg.getBoundingClientRect();
    const viewX = ((event.clientX - rect.left) / rect.width) * CHART.width;
    const nearest = visibleTimelinePoints.reduce((best, point, index) => Math.abs(timelineX(point) - viewX) < Math.abs(timelineX(visibleTimelinePoints[best]) - viewX) ? index : best, 0);
    showTimelinePoint(nearest);
  });
  svg.addEventListener("pointerleave", () => {
    if (document.activeElement !== svg) hideTimelinePoint();
  });
  svg.addEventListener("focus", () => showTimelinePoint(timelineFocusIndex < 0 ? visibleTimelinePoints.length - 1 : timelineFocusIndex));
  svg.addEventListener("blur", hideTimelinePoint);
  svg.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !visibleTimelinePoints.length) return;
    event.preventDefault();
    if (event.key === "Home") timelineFocusIndex = 0;
    else if (event.key === "End") timelineFocusIndex = visibleTimelinePoints.length - 1;
    else timelineFocusIndex += event.key === "ArrowRight" ? 1 : -1;
    showTimelinePoint(timelineFocusIndex);
  });
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
  renderTimeline();
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
  document.getElementById("asof").textContent = `Data as of ${payload.asof} · Updated ${generated.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
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
  bindTimelineControls();
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
      return loadJson("data/timeline.json")
        .then((timeline) => {
          timelinePayload = validateTimeline(timeline);
          renderTimeline();
        })
        .catch(() => {
          document.getElementById("timeline-latest").textContent = "Timeline data is temporarily unavailable.";
          document.getElementById("timeline-chart").setAttribute("hidden", "");
          document.getElementById("timeline-methodology").textContent = "The current scores remain available.";
          document.getElementById("timeline-state").textContent = "The timeline will return after its next validated publication.";
          document.getElementById("timeline-state").classList.add("is-visible");
        });
    })
    .catch(() => {
      document.getElementById("asof").textContent = "Market data is temporarily unavailable";
      document.getElementById("warmup").textContent = "The latest reading did not pass the public data contract.";
      observeReveals();
    });
}

if (typeof module !== "undefined") {
  module.exports = { indicatorBand, publicLanguage, timelineRange, validatePayload, validateTimeline, visualCoordinate };
  if (require.main === module) {
    const fs = require("node:fs");
    const data = JSON.parse(fs.readFileSync("data/scores.json", "utf8"));
    validatePayload(data);
    if (fs.existsSync("data/timeline.json")) validateTimeline(JSON.parse(fs.readFileSync("data/timeline.json", "utf8")));
    console.assert(indicatorBand(80, "panic")[0] === "high pressure");
    console.assert(indicatorBand(50, "fundamentals")[0] === "mixed evidence");
    console.assert(visualCoordinate(80, 80).y < visualCoordinate(80, 30).y);
    console.assert(timelineRange([{ date: "2025-01-01" }, { date: "2026-01-01" }], "1M").length === 1);
    console.assert(timelineRange([{ date: "2026-02-28" }, { date: "2026-03-31" }], "1M").length === 2);
    console.assert(publicLanguage("Golden Zone / Fundamentals") === "Candidate Dislocation / Consensus Earnings Health");
  }
}
