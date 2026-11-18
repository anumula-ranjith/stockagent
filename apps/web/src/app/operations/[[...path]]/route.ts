import type { NextRequest } from "next/server";
import { proxy } from "@/lib/proxy";

async function handle(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return proxy(request, (await context.params).path ?? [], true);
}

export { handle as GET, handle as POST, handle as HEAD };
