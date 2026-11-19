import { queryOptions } from "@tanstack/react-query";
import { defaults, type Settings, type Snapshot } from "@/app/dashboard/ranker-model";
import { api } from "./api";

// Home, navigation prefetch and the tuner must share both shape and identity.
export function rankingQuery(user: string | undefined, date = "", settings: Settings = defaults) {
  return queryOptions({
    queryKey: ["ranker", user, date, settings],
    enabled: !!user,
    queryFn: async ({ signal }) => ({
      ...await api<Snapshot>("/ranker/snapshot" + (date ? "?asof=" + date : ""), {
        method: "POST", signal, body: JSON.stringify(settings),
      }),
      settings,
    }),
  });
}
