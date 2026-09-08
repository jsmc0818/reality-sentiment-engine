/* Transparent research heuristics and a five-year FCFF sensitivity model.
 * Kept dependency-free so the browser and CI run exactly the same valuation.
 */
(function (root) {
  "use strict";
  const finite = Number.isFinite;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const METHOD = "expectations-v1";

  function ageDays(date, now = new Date()) {
    const start = Date.parse(`${date}T00:00:00Z`);
    if (!finite(start) || new Date(start).toISOString().slice(0, 10) !== date) return Infinity;
    return Math.floor((now - start) / 86400000);
  }

  function marketAge(date, now = new Date()) {
    let end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    if (now.getUTCHours() < 21) end.setUTCDate(end.getUTCDate() - 1);
    while ([0, 6].includes(end.getUTCDay())) end.setUTCDate(end.getUTCDate() - 1);
    const start = new Date(`${date}T00:00:00Z`);
    if (!finite(start.getTime()) || start > end) return Infinity;
    let age = 0;
    for (let d = new Date(start); d < end;) {
      d.setUTCDate(d.getUTCDate() + 1);
      if (![0, 6].includes(d.getUTCDay())) age++;
    }
    return age;
  }

  function evidence(stock, now = new Date()) {
    const m = stock.market, f = stock.financials;
    if (!m || !f || stock.status !== "available") return {code: "limited", label: "Limited evidence", ready: false};
    const collectionAge = ageDays(stock.collected_at.slice(0, 10), now);
    const incomeAge = ageDays(f.period_end, now), balanceAge = ageDays(f.balance_date, now);
    if (marketAge(m.price_date, now) > 1 || collectionAge < 0 || collectionAge > 4 ||
        incomeAge < 0 || incomeAge > 150 || balanceAge < 0 || balanceAge > 200) {
      return {code: "stale", label: "Stale evidence", ready: false};
    }
    return {code: "available", label: "Dated evidence", ready: true};
  }

  function resilience(stock) {
    const f = stock.financials;
    if (!f || !finite(f.revenue_growth_yoy_pct) || !finite(f.margin_change_yoy_pts)) {
      return {code: "unknown", label: "Incomplete", detail: "Comparable revenue and margin evidence required."};
    }
    const growth = f.revenue_growth_yoy_pct, margin = f.margin_change_yoy_pts;
    const netDebt = f.debt - f.cash;
    if (growth < -5 || margin < -3 || f.operating_income <= 0 ||
        (netDebt > 0 && (f.operating_cash_flow <= 0 || netDebt > 4 * f.operating_cash_flow))) {
      return {code: "weakening", label: "Weakening", detail: "At least one material growth, margin, profitability or leverage warning."};
    }
    if (growth >= 0 && margin >= -1 && f.free_cash_flow > 0 &&
        (netDebt <= 0 || (f.operating_cash_flow > 0 && netDebt <= 3 * f.operating_cash_flow))) {
      return {code: "resilient", label: "Resilient", detail: "Nonnegative sales growth, broadly stable margins, positive free cash flow and contained leverage."};
    }
    return {code: "mixed", label: "Mixed", detail: "Evidence does not clear the resilience checks. Inspect capital spending and margin direction."};
  }

  function defaults(stock) {
    const f = stock.financials;
    if (!f || !finite(f.revenue_growth_yoy_pct)) return null;
    return {growth: Math.round(clamp(f.revenue_growth_yoy_pct, 0, 25) * 2) / 2,
      margin: Math.round(clamp(f.operating_margin_pct, 1, 65) * 2) / 2,
      discount: 10, terminal: 3, tax: 21, capital: 2};
  }

  function validInputs(a) {
    return a && [a.growth, a.margin, a.discount, a.terminal, a.tax, a.capital].every(finite) &&
      a.growth >= -10 && a.growth <= 60 && a.margin >= 0 && a.margin <= 70 &&
      a.discount >= 6 && a.discount <= 20 && a.terminal >= 0 && a.terminal <= 4 &&
      a.discount > a.terminal && a.tax >= 0 && a.tax <= 40 && a.capital >= .5 && a.capital <= 5;
  }

  function value(stock, a) {
    const f = stock.financials, m = stock.market;
    if (!f || !m || !validInputs(a) || ![f.revenue, f.operating_margin_pct, f.cash, f.debt, m.market_cap, m.price].every(finite) ||
        f.revenue <= 0 || m.market_cap <= 0 || m.price <= 0) return null;
    let revenue = f.revenue, pv = 0;
    const flows = [];
    for (let year = 1; year <= 5; year++) {
      const prior = revenue;
      revenue *= 1 + a.growth / 100;
      const margin = (f.operating_margin_pct + (a.margin - f.operating_margin_pct) * year / 5) / 100;
      // No assumed liquidation windfall when revenue contracts.
      const reinvestment = Math.max(0, revenue - prior) / a.capital;
      const fcff = revenue * margin * (1 - a.tax / 100) - reinvestment;
      const present = fcff / (1 + a.discount / 100) ** year;
      pv += present;
      flows.push({year, revenue, margin, reinvestment, fcff, present});
    }
    const terminalRevenue = revenue * (1 + a.terminal / 100);
    const terminalCash = terminalRevenue * a.margin / 100 * (1 - a.tax / 100) - (terminalRevenue - revenue) / a.capital;
    const terminalPV = terminalCash / ((a.discount - a.terminal) / 100) / (1 + a.discount / 100) ** 5;
    const enterprise = pv + terminalPV;
    const equity = Math.max(0, enterprise + f.cash - f.debt);
    const price = equity / m.market_cap * m.price;
    return {price, enterprise, equity, upside: (price / m.price - 1) * 100,
      cushion: price > 0 ? (1 - m.price / price) * 100 : null,
      terminalShare: enterprise > 0 ? terminalPV / enterprise * 100 : null, flows};
  }

  function scenarios(stock, a = defaults(stock)) {
    if (!a) return null;
    return {
      bear: value(stock, {...a, growth: clamp(a.growth - 5, -10, 60), margin: Math.max(0, a.margin - 3), discount: Math.min(20, a.discount + 2)}),
      base: value(stock, a),
      bull: value(stock, {...a, growth: Math.min(60, a.growth + 5), margin: Math.min(70, a.margin + 3), discount: Math.max(6, a.discount - 1)}),
    };
  }

  function impliedGrowth(stock, a) {
    if (!validInputs(a)) return null;
    // Scan for EVERY crossing: high reinvestment can make value non-monotonic.
    const crossings = [];
    let lo = -10, left = value(stock, {...a, growth: lo});
    if (!left) return null;
    for (let hi = -9.5; hi <= 60; hi += .5) {
      const right = value(stock, {...a, growth: hi});
      if (!right) return null;
      if ((left.price - stock.market.price) * (right.price - stock.market.price) <= 0) {
        let l = lo, h = hi, fl = left.price - stock.market.price;
        for (let i = 0; i < 35; i++) {
          const mid = (l + h) / 2;
          const fm = value(stock, {...a, growth: mid}).price - stock.market.price;
          if (fl * fm <= 0) h = mid; else { l = mid; fl = fm; }
        }
        const found = (l + h) / 2;
        if (!crossings.some(x => Math.abs(x - found) < .01)) crossings.push(found);
      }
      lo = hi; left = right;
    }
    return {roots: crossings, lower: -10, upper: 60};
  }

  const STATES = {
    fear: {label: "Fear discount candidate", tone: "green", detail: "Selling pressure, resilient financial evidence and a reference discount. Challenge assumptions before accumulating."},
    fragile: {label: "Discount, fragile evidence", tone: "amber", detail: "Reference valuation suggests a discount, but business evidence does not support a resilient label."},
    optimism: {label: "Optimism priced in", tone: "red", detail: "Buying pressure coincides with a premium to the reference model. Stronger execution may justify it."},
    demanding: {label: "Demanding valuation", tone: "amber", detail: "Current price exceeds the reference scenario. This is model sensitivity, not proof of overvaluation."},
    discount: {label: "Reference discount", tone: "green", detail: "Price sits below the reference scenario without a strong fear signal."},
    neutral: {label: "Near reference value", tone: "neutral", detail: "Price clears neither the 20% discount nor the 15% premium threshold. Inspect assumptions and company evidence."},
    unclear: {label: "Unclear", tone: "neutral", detail: "Fresh, sufficient evidence and a valid model are required before classification."},
  };

  function classify(stock, a = defaults(stock), now = new Date()) {
    if (!evidence(stock, now).ready || !a) return {code: "unclear", ...STATES.unclear};
    const v = value(stock, a), r = resilience(stock);
    if (!v || r.code === "unknown") return {code: "unclear", ...STATES.unclear};
    const discount = v.cushion !== null && v.cushion >= 20;
    let code = "neutral";
    if (discount && r.code !== "resilient") code = "fragile";
    else if (discount && stock.market.mood <= 30) code = "fear";
    else if (discount) code = "discount";
    else if (v.price < stock.market.price / 1.15) code = stock.market.mood >= 70 ? "optimism" : "demanding";
    return {code, ...STATES[code]};
  }

  const api = {METHOD, ageDays, marketAge, evidence, resilience, defaults, validInputs, value, scenarios, impliedGrowth, classify, STATES};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ResearchModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
