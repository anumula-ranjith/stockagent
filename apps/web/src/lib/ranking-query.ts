import type { UniverseOptions, UniverseSelection } from "@/components/universe-filters";
import { queryOptions } from "@tanstack/react-query";
import { defaults, type Settings, type Snapshot } from "@/app/dashboard/ranker-model";
import { api } from "./api";

// Home, navigation prefetch and the tuner must share both shape and identity.
export function rankingQuery(user: string | undefined, date = "", settings: Settings = defaults, selection?: UniverseSelection) {
  const params = new URLSearchParams();
  if (date) params.set("asof", date);
  if (selection) {
    params.set("universe_filters", "true");
    for (const [key,value] of Object.entries(selection)) params.set(key,String(value));
  }
  return queryOptions({
    queryKey: ["ranker", user, date, settings, selection],
    enabled: !!user,
    refetchInterval: date ? false : 60_000,
    queryFn: async ({ signal }) => ({
      ...await api<Snapshot & UniverseOptions>("/ranker/snapshot" + (params.size ? "?" + params : ""), {
        method: "POST", signal, body: JSON.stringify(settings),
      }),
      settings,
    }),
  });
}
