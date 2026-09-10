"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const M = require("../model.js");
const {validateStocks} = require("../app.js");
const now = new Date("2026-09-08T23:00:00Z");
const stock = {status:"available",collected_at:now.toISOString(),market:{price:100,market_cap:1000,mood:20,price_date:"2026-09-08"},financials:{period_end:"2026-06-30",balance_date:"2026-06-30",revenue:1000,operating_income:200,operating_margin_pct:20,revenue_growth_yoy_pct:10,margin_change_yoy_pts:0,operating_cash_flow:200,free_cash_flow:150,cash:100,debt:0}};
const a = {growth:0,margin:20,discount:10,terminal:0,tax:0,capital:2};
// No-growth perpetuity: enterprise 200 / 10% = 2000, cash adds 100.
assert.ok(Math.abs(M.value(stock,a).price-210)<1e-9);
assert.ok(M.value(stock,{...a,discount:12}).price < M.value(stock,a).price);
assert.ok(M.value(stock,{...a,margin:25}).price > M.value(stock,a).price);
assert.equal(M.value(stock,{...a,discount:3,terminal:3}),null);
assert.equal(M.value(stock,{...a,growth:NaN}),null);
assert.equal(M.resilience(stock).code,"resilient");
assert.equal(M.classify(stock,a,now).code,"fear");
const weak=structuredClone(stock);weak.financials.revenue_growth_yoy_pct=-20;
assert.equal(M.classify(weak,a,now).code,"fragile");
const stale=structuredClone(stock);stale.market.price_date="2026-07-01";
assert.equal(M.classify(stale,a,now).code,"unclear");
const future=structuredClone(stock);future.market.price_date="2026-09-09";
assert.equal(M.classify(future,a,now).code,"unclear");
const target=M.value(stock,{...a,growth:12});
const calibrated=structuredClone(stock);calibrated.market.market_cap=target.equity;
const solution=M.impliedGrowth(calibrated,a);
assert.ok(solution.roots.some(r=>Math.abs(r-12)<.001));
assert.equal(M.marketAge("2026-09-04",new Date("2026-09-06T23:00:00Z")),0);
const observed=validateStocks(JSON.parse(fs.readFileSync(path.join(__dirname,"../data/stocks.json"))));
for(const s of observed.stocks.filter(s=>s.status==="available" && M.defaults(s))) {
  const d=M.defaults(s), cases=M.scenarios(s,d);
  assert.ok([cases.bear.price,cases.base.price,cases.bull.price].every(Number.isFinite));
  assert.ok(cases.bear.price>=0 && cases.bull.price>=0);
  for(const root of M.impliedGrowth(s,d).roots) assert.ok(Math.abs(M.value(s,{...d,growth:root}).price-s.market.price)<.01);
}
// Run browser entrypoint with a tiny DOM harness: verifies IDs, fetch, and
// all seven detail paths without installing a framework or making live calls.
const html=fs.readFileSync(path.join(__dirname,"../index.html"),"utf8");
const listeners = {};
const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(([,id])=>[id,{innerHTML:"",textContent:"",hidden:false,addEventListener(type, handler){this[type]=handler;},scrollIntoView(){}}]));
const sandbox={ResearchModel:M,console,Date,Intl,Number,Promise,history:{replaceState(){}},location:{hash:""},fetch:async url=>({ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(__dirname,"..",url)))}),document:{querySelectorAll:()=>[],getElementById:id=>{if(!elements.has(id)&&!id.startsWith("output-"))throw new Error(`Missing HTML id: ${id}`);return elements.get(id);},addEventListener(type,handler){listeners[type]=handler;}},window:{ResearchModel:M,matchMedia:()=>({matches:true})}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,"../app.js"),"utf8"),sandbox);
setImmediate(()=>{
  assert.ok(elements.get("watchlist-body").innerHTML.includes("MSFT"));
  assert.equal((elements.get("signal-status").innerHTML.match(/class="signal-row /g)||[]).length,7);
  for(const symbol of observed.stocks.map(s=>s.symbol)) {
    vm.runInContext(`selectStock('${symbol}')`,sandbox);
    assert.ok(elements.get("stock-detail").innerHTML.includes(symbol));
    assert.ok(elements.get("history-content").innerHTML.includes("Six-month market path"));
  }
  elements.get("state-filter").change({target:{value:"unclear"}});
  assert.ok(!elements.get("watchlist-body").innerHTML.includes('data-symbol="MSFT"'));
  assert.equal((elements.get("signal-status").innerHTML.match(/class="signal-row /g)||[]).length,7);
  vm.runInContext("selectStock('AMZN')",sandbox);
  assert.equal(elements.get("lab").hidden,true);
  let redirected=false;
  listeners.click({target:{closest:selector=>selector==='a[href^="#"]' ? {getAttribute:()=>"#lab"} : null},preventDefault(){redirected=true;}});
  assert.ok(redirected,"Unavailable valuation must navigate to visible company evidence");
  console.log("Valuation economics, reverse solutions, stale gates and seven stock UI paths passed");
});
