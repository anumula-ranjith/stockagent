import { defaults, type Settings } from "@/app/dashboard/ranker-model";
import { parseScreen, type ScreenFilters } from "./screen-filters";

export const standardPeriods = {
  ema_fast: 9, ema_slow: 21, ema_sessions_ago: 0,
  macd_fast: 12, macd_slow: 26, macd_signal: 9, macd_sessions_ago: 0,
};
export type Periods = typeof standardPeriods;
export type CrossoverRule = "any" | "above" | "below" | "cross_up" | "cross_down";
export type ChartRules = {ema_rule: CrossoverRule; macd_rule: CrossoverRule};
export const standardRules: ChartRules = {ema_rule: "any", macd_rule: "any"};
export type StockQuery = Record<string, string | string[] | undefined>;
export const periodKeys = Object.keys(standardPeriods) as (keyof Periods)[];

export function stockHref(ticker: string, context: {periods?: Periods; rules?: ChartRules; settings?: Settings; asof?: string; screen?: ScreenFilters} = {}) {
  const query = new URLSearchParams();
  if (context.screen) query.set("screen", JSON.stringify(context.screen));
  if (context.asof) query.set("asof", context.asof);
  if (context.periods) {
    for (const key of periodKeys) {
      if (context.periods[key] !== standardPeriods[key]) query.set(key, String(context.periods[key]));
    }
  }
  if (context.rules) {
    for (const key of ["ema_rule", "macd_rule"] as const) {
      if (context.rules[key] !== standardRules[key]) query.set(key, context.rules[key]);
    }
  }
  if (context.settings) {
    const changed = Object.fromEntries(Object.entries(context.settings).filter(([key, value]) =>
      JSON.stringify(value) !== JSON.stringify(defaults[key as keyof Settings])));
    if (Object.keys(changed).length) query.set("ranking", JSON.stringify(changed));
  }
  const suffix = query.toString();
  return "/stocks/" + encodeURIComponent(ticker) + (suffix ? "?" + suffix : "");
}

export function stockContext(query: StockQuery) {
  const periods = {...standardPeriods};
  const rules = {...standardRules};
  for (const key of periodKeys) {
    const value = query[key];
    if (typeof value === "string" && /^\d{1,3}$/.test(value)) periods[key] = Number(value);
  }
  for (const key of ["ema_rule", "macd_rule"] as const) {
    const value = query[key];
    if (typeof value === "string" && ["any", "above", "below", "cross_up", "cross_down"].includes(value)) {
      rules[key] = value as CrossoverRule;
    }
  }
  let settings: Settings | undefined;
  if (typeof query.ranking === "string" && query.ranking.length <= 8000) {
    try {
      const parsed = JSON.parse(query.ranking);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const valid = Object.keys(defaults).filter(key => Object.hasOwn(parsed, key));
        settings = {...defaults, ...Object.fromEntries(valid.map(key => [key, parsed[key]]))};
      }
    } catch { /* Malformed external links open with the dashboard defaults. */ }
  }
  const asof = typeof query.asof === "string" && /^\d{4}-\d{2}-\d{2}$/.test(query.asof) ? query.asof : undefined;
  const screen = typeof query.screen === "string" ? parseScreen(query.screen) : undefined;
  return {periods, rules, settings, asof, screen};
}
