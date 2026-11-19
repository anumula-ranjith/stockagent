import type { components } from "./api-types";

type Schemas = components["schemas"];
export type User = Schemas["UserOut"];
export type Health = Schemas["HealthOut"];
export type UniverseRow = Schemas["UniverseRow"];
export type PriceBar = Schemas["PriceBar"];
export type NewsItem = Schemas["NewsItem"];
export type ScoreRow = Schemas["AgentScoreRow"];
export type HistoryPoint = Schemas["AgentHistoryPoint"];
export type Combine = Schemas["CombineOut"];
export type RankedStock = Schemas["CombineRow"];
export type JobRef = Schemas["BacktestJobRef"];
export type JobStatus = Schemas["JobStatusOut"];
export type LoginBody = Schemas["LoginRequest"];

export const agents = ["technical", "sentiment", "momentum", "fundamental"] as const;
export type Agent = typeof agents[number];
export const agentLabels: Record<Agent, string> = {
  technical: "Technical", sentiment: "Sentiment", momentum: "Momentum", fundamental: "Fundamental",
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && !["GET", "HEAD"].includes(init.method.toUpperCase())) headers.set("X-Stock-Agents-Request", "1");
  if (typeof init.body === "string") headers.set("Content-Type", "application/json");
  const base = (process.env.NEXT_PUBLIC_API_BASE || "/backend").replace(/\/$/, "");
  const response = await fetch(base + path, {
    ...init, headers, credentials: "same-origin", cache: "no-store",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = typeof data?.detail === "string" ? data.detail : null;
    throw new ApiError(response.status, response.status === 429
      ? "Rate limit reached. Try again later."
      : detail || (response.status === 422 ? "Check the inputs and try again." : "The request could not be completed."));
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}
