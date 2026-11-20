"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import dynamic from "next/dynamic";
import { type ReactNode, useState } from "react";
import { api, ApiError, type User } from "@/lib/api";

const ClerkShell = dynamic(() => import("./clerk-shell"));
export const usesClerk = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => {
    const cache = new QueryClient({defaultOptions: {queries: {
      staleTime: 45_000, gcTime: 30 * 60_000, retry: false,
    }}});
    // EOD observations can be reused across page visits. Account and job queries
    // retain their own freshness rules and explicit mutation invalidation.
    for (const key of ["universe", "price", "ranker", "nifty-screen", "stock-indicators", "stock-profile", "stock-agent-analysis", "agent", "history", "news"]) {
      cache.setQueryDefaults([key], {staleTime: 5 * 60_000, refetchOnWindowFocus: false});
    }
    return cache;
  });
  const app = <QueryClientProvider client={client}><NuqsAdapter>{children}</NuqsAdapter></QueryClientProvider>;
  return <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem disableTransitionOnChange>
    {usesClerk ? <ClerkShell>{app}</ClerkShell> : app}
  </ThemeProvider>;
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try { return await api<User>("/me"); }
      catch (error) { if (error instanceof ApiError && error.status === 401) return null; throw error; }
    },
  });
}
