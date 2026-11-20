import { agents, type Agent } from "@/lib/api";

export type Tab = Agent | "combined" | "portfolio";
type Factor = readonly [key:string,label:string,weight:number];
export const factors: Record<Exclude<Agent,"fundamental">, Factor[]> = {
  technical: [
    ["rsi14","RSI (14)",5],["macd_hist","MACD histogram",5],["vs_sma50","Price vs 50-day avg",5],
    ["vs_sma200","Price vs 200-day avg",5],["golden_cross","Golden cross",3],["adx14_signed","Trend strength (ADX)",5],
    ["bb_pctb","Bollinger %B",3],["stoch_k","Stochastic %K",3],["vol_surge","Volume surge",5],
    ["obv_trend","On-balance volume trend",5],["atr_pct","Low volatility (ATR %)",3],["prox_52w_high","Near 52-week high",5],
  ],
  sentiment: [
    ["news_tone_7d","News tone (7-day)",8],["news_volume","News volume vs normal",3],["news_attention_7d","News attention (7-day)",3],["hot_sector","Hot sector",6],
    ["est_revisions","Analyst revisions",6],["rating_change_1m","Rating change (1 month)",4],["social_buzz","Social buzz (not connected)",0],["insider_activity","Insider buying",3],["short_interest","Short interest (unavailable)",0],
    ["nse_short_selling_activity","NSE short sales / volume (120 sessions)",3],
  ],
  momentum: [
    ["ret_1m","1-month return",3],["ret_3m","3-month return",6],["ret_6m","6-month return",7],
    ["ret_12_1","12–1 month return",9],["rel_str","Strength vs market (3M)",3],["accel","Acceleration",2],
  ],
};
export const pillars: [string,string,number,[string,string][]][] = [
  ["value","Value",25,[["pe_ttm","P/E (lower better)"],["forward_pe","Forward P/E (lower better)"],["price_to_book","Price / book"],["ev_ebitda","EV / EBITDA"],["price_to_sales","Price / sales"],["fcf_yield","FCF yield"],["peg","PEG"]]],
  ["quality","Quality",25,[["roe_ttm","Return on equity"],["roa_ttm","Return on assets"],["roic","Return on invested capital"],["gross_margin","Gross margin"],["operating_margin_ttm","Operating margin"],["net_margin_ttm","Net margin"]]],
  ["growth","Growth",25,[["revenue_growth_yoy","Revenue growth"],["eps_growth_yoy","EPS growth"],["eps_surprise","EPS surprise"],["forward_eps_growth","Forward EPS growth"]]],
  ["health","Health",15,[["debt_equity","Debt / equity"],["current_ratio","Current ratio"],["interest_coverage","Interest coverage"]]],
  ["shareholder_yield","Shareholder yield",10,[["dividend_yield","Dividend yield"],["buyback_yield","Buyback yield"]]],
];
export const defaults = {
  factors: Object.fromEntries([...Object.values(factors).flat().map(([key,,weight])=>[key,weight]), ...pillars.flatMap(([, , ,items])=>items.map(([key])=>[key,1]))]) as Record<string,number>,
  agents:Object.fromEntries(agents.map(a=>[a,25])) as Record<Agent,number>,
  pillars:Object.fromEntries(pillars.map(([key,,weight])=>[key,weight])) as Record<string,number>,
  size:10, max_sector:3, agree:3, mode:"weighted", rsi_min:30, rsi_max:80, tech_above_ma:false,
  min_traded_value:0, vol_adjust:false, mom_above_ma:false, min_headlines:3, boost_sectors:true, short_squeeze:false,
  sector_neutral:true, max_pe:0, max_de:0, positive_fcf:false,
};
export type Settings = typeof defaults;
export type Snapshot = {
  asof:string; price_date:string|null; universe:number; coverage:Record<string,number>;
  rows:Record<string,{ticker:string;sector:string;values:Record<string,number>}>;
  books:Record<Exclude<Tab,"portfolio">,{longs:string[];shorts:string[]}>;
  heat:{sector:string;value:number}[];
};
export const columns:Record<Agent,[string,string,("percent"|"volumePercent"|"ratio"|"number")?][]> = {
  technical:[["rsi14","RSI"],["vs_sma50","vs 50d","percent"],["vs_sma200","vs 200d","percent"],["adx14_signed","ADX"],["vol_surge","Vol surge","ratio"],["technical","Score"]],
  sentiment:[["news_tone_7d","News tone","ratio"],["headlines","Headlines 7d"],["est_revisions","Revisions"],["social_buzz","Social"],["insider_activity","Net insider"],["short_interest","Short interest","percent"],["nse_short_selling_activity","NSE short sales / volume (120 sessions)","volumePercent"],["sentiment","Score"]],
  momentum:[["ret_1m","1M","percent"],["ret_3m","3M","percent"],["ret_6m","6M","percent"],["ret_12_1","12–1M","percent"],["rel_str","Relative","percent"],["accel","Accel.","percent"],["momentum","Score"]],
  fundamental:[["pe_ttm","P/E","ratio"],["roe_ttm","ROE","percent"],["revenue_growth_yoy","Rev growth","percent"],["debt_equity","D/E","ratio"],["dividend_yield","Yield","percent"],["fundamental","Score"]],
};
export function display(value:number|undefined, kind?:string) {
  if(value==null || !Number.isFinite(value)) return "—";
  if(kind==="percent") return (value>0?"+":"")+(100*value).toFixed(1)+"%";
  if(kind==="volumePercent") return (100*value).toFixed(3)+"%";
  if(kind==="ratio") return value.toFixed(2);
  return Math.round(value).toLocaleString("en-IN");
}
