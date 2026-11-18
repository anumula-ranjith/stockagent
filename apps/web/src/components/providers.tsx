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
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 45_000, retry: false } },
  }));
  const app = <QueryClientProvider client={client}><NuqsAdapter>{children}</NuqsAdapter></QueryClientProvider>;
  return <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem>
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
