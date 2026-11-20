import { queryOptions } from "@tanstack/react-query";
import { api } from "./api";
import type { components } from "./api-types";
import { defaultScreen, screenRequest } from "./screen-filters";

export function screenQuery(user: string, filters = defaultScreen) {
  return queryOptions({
    queryKey: ["nifty-screen", user, filters],
    queryFn: async ({signal}) => ({...await api<components["schemas"]["ScreenResult"]>("/screener/run", {
      method: "POST", signal, body: JSON.stringify(screenRequest(filters)),
    }), filters}),
  });
}
