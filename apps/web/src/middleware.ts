import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

const clerk = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk" ? clerkMiddleware() : null;

export default function middleware(request: NextRequest, event: NextFetchEvent) {
  return clerk ? clerk(request, event) : NextResponse.next();
}

export const config = { matcher: ["/backend/:path*", "/operations/:path*", "/_admin/rq/:path*", "/login/:path*"] };
