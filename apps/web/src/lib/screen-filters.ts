import { z } from "zod";

export function validDistance(value: string) {
  return value === "" || (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)
    && Number(value) >= -100 && Number(value) <= 10000);
}

const screenSchema = z.object({
  index_code: z.string().regex(/^NIFTY[A-Z0-9]{1,30}$/),
  cap: z.enum(["", "large", "mid", "small"]),
  industry: z.string().max(150),
  fo_only: z.boolean(),
  reference: z.enum(["high", "low"]),
  distance: z.string().max(40).refine(validDistance),
  heikin_ashi_rule: z.enum(["any", "green_to_red", "red_to_green"]),
});
export type ScreenFilters = z.infer<typeof screenSchema>;
export const defaultScreen: ScreenFilters = {
  index_code: "NIFTY500", cap: "", industry: "", fo_only: false,
  reference: "high", distance: "", heikin_ashi_rule: "any",
};

export function parseScreen(raw?: string | null): ScreenFilters | undefined {
  if (!raw || raw.length > 2000) return;
  try {
    return screenSchema.safeParse(JSON.parse(raw)).data;
  } catch { return; }
}

export const screenStorageKey = (user: string) => "nifty-screener:v1:" + user;
export function savedScreen(user: string) {
  try { return parseScreen(window.localStorage.getItem(screenStorageKey(user))) ?? defaultScreen; }
  catch { return defaultScreen; }
}

export function screenRequest(screen: ScreenFilters) {
  const {reference, distance, cap, industry, ...filters} = screen;
  const pct = Number(distance);
  const range = distance === "" ? {} : {[(pct < 0 ? "below_" : "above_") + reference + "_pct"]: Math.abs(pct)};
  return {...filters, ...range, cap: cap || null, industry: industry || null};
}

export const candleLabels = {
  any: "Any candle", green_to_red: "Green → Red", red_to_green: "Red → Green",
};

export function screenDescription(screen: ScreenFilters) {
  const pct = Number(screen.distance);
  const level = "52-week " + screen.reference;
  const range = screen.distance === "" ? "Any 52-week distance" : pct === 0 ? "At the " + level
    : `Within ${Math.abs(pct)}% ${pct < 0 ? "below" : "above"} the ${level}`;
  return [screen.index_code, screen.cap ? screen.cap + " cap" : "All sizes",
    screen.industry || "All industries", screen.fo_only ? "F&O eligible only" : "All F&O statuses",
    range, "Heikin Ashi · " + candleLabels[screen.heikin_ashi_rule]].join(" · ");
}

export function intradayLabel(result: {price_source?: string | null; exchange_trade_at?: string | null}) {
  if (result.price_source === "mixed") return "Mixed price sources";
  if (result.price_source !== "angel_one") return null;
  const date = result.exchange_trade_at ? new Date(result.exchange_trade_at) : null;
  if (!date || !Number.isFinite(date.valueOf())) return "Angel One · intraday";
  const time = date.toLocaleTimeString("en-IN", {timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true});
  return `Angel One · ${time} IST · intraday`;
}
