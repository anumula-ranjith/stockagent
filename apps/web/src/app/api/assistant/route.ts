import { NextRequest } from "next/server";
import { proxy } from "@/lib/proxy";

export const runtime = "nodejs";

const context = `You are QUANTORA's private product assistant. Answer questions about the product and help the signed-in user discuss ideas, bugs and workflows. Product facts: QUANTORA covers NSE India stocks; the dashboard ranks Nifty 500 stocks with technical, sentiment, momentum and fundamental factors, plus combined rankings and portfolio backtests. The wider directory includes NSE F&O names. The screener, stock pages, watchlists and portfolios are separate tools. EODHD supplies prices, some fundamentals, news and sentiment; licensed FactSet supplies some financial and analyst inputs. Data coverage varies by stock and date. Historical point-in-time coverage is limited. Explain uncertainty and suggest checking the dashboard or methodology for live figures. Do not claim access to the user's private portfolio, account, current data or internal documents: this chat has only this product description and conversation messages. Never reveal secrets or speculate about unpublished plans. Keep answers concise and practical.`;

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  // Next may use an internal URL behind the local server or a reverse proxy.
  // Compare against the public Host header, as the backend proxy does.
  const host = request.headers.get("host");
  const expected = host ? `${request.nextUrl.protocol}//${host}` : request.nextUrl.origin;
  if (origin && origin !== expected) return Response.json({ detail: "Invalid origin" }, { status: 403 });
  if (request.headers.get("x-stock-agents-request") !== "1") return Response.json({ detail: "Invalid request" }, { status: 403 });
  const auth = await proxy(new NextRequest(new URL("/backend/me", request.url), { headers: request.headers }), ["me"]);
  if (!auth.ok) return Response.json({ detail: "Sign in to use the assistant" }, { status: 401 });
  const key = process.env.OPENAI_API_KEY;
  if (!key) return Response.json({ detail: "AI assistant is not configured. Set OPENAI_API_KEY for the web server, then restart it." }, { status: 503 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ detail: "Invalid JSON" }, { status: 400 }); }
  if (!body || typeof body !== "object" || !("messages" in body) || !Array.isArray(body.messages)) {
    return Response.json({ detail: "Messages are required" }, { status: 400 });
  }
  const messages = body.messages;
  if (messages.length < 1 || messages.length > 20 || messages.some(m => !m || !["user", "assistant"].includes(m.role)
    || typeof m.content !== "string" || !m.content.trim() || m.content.length > 3000)
    || messages.at(-1).role !== "user") {
    return Response.json({ detail: "Invalid conversation" }, { status: 400 });
  }
  try {
    const upstream = await fetch("https://api.openai.com/v1/responses", {
      method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: process.env.OPENAI_CHAT_MODEL || "gpt-4.1-mini", instructions: context,
        input: messages, max_output_tokens: 700, store: false }),
      signal: AbortSignal.timeout(45000), cache: "no-store",
    });
    if (!upstream.ok) return Response.json({ detail: "The AI provider is unavailable. Try again shortly." }, { status: 502 });
    const result = await upstream.json();
    const answer = result.output?.flatMap((item: { content?: { type?: string; text?: string }[] }) => item.content || [])
      .filter((item: { type?: string }) => item.type === "output_text")
      .map((item: { text?: string }) => item.text || "").join("\n").trim();
    if (!answer) return Response.json({ detail: "The assistant returned no text" }, { status: 502 });
    return Response.json({ answer }, { headers: { "Cache-Control": "private, no-store" } });
  } catch {
    return Response.json({ detail: "The AI provider timed out. Try again." }, { status: 502 });
  }
}
