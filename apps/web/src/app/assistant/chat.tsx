"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useSession } from "@/components/providers";
import styles from "./assistant.module.css";

type Message = { role: "user" | "assistant"; content: string };
const starters = ["How does the combined ranking work?", "What data is missing from the dashboard?", "How should we improve the product?"];

export function AssistantChat({ compact = false }: { compact?: boolean }) {
  const session = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send(event?: FormEvent, suggestion?: string) {
    event?.preventDefault();
    const content = (suggestion ?? draft).trim();
    if (!content || busy) return;
    const next: Message[] = [...messages.slice(-18), { role: "user", content }];
    setMessages(next); setDraft(""); setError(""); setBusy(true);
    try {
      const response = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json", "X-Stock-Agents-Request": "1" }, body: JSON.stringify({ messages: next }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Assistant unavailable");
      setMessages([...next, { role: "assistant", content: data.answer }]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Assistant unavailable"); }
    finally { setBusy(false); }
  }
  return <div className={compact ? styles.compact : "shell workspace"}>{!compact && <div className={styles.head}><span className="eyebrow">Private workspace</span><h1>Product assistant</h1>
    <p>Discuss QUANTORA features, scoring, data coverage and product ideas. This conversation stays in this browser session.</p></div>}
    {session.isPending ? <p>Checking your session…</p> : !session.data ? <div className={styles.empty}>Sign in to use the private assistant. <Link href="/login?next=%2Fassistant">Sign in</Link></div>
      : <div className={styles.chat}><div className={styles.messages} role="log" aria-live="polite">
        {messages.length === 0 && <div className={styles.empty}><strong>What would you like to discuss?</strong><p>Ask about the product or start with a suggestion.</p>
          <div className={styles.starters}>{starters.map(s => <button key={s} onClick={() => void send(undefined, s)}>{s}</button>)}</div></div>}
        {messages.map((message, i) => <div key={i} className={message.role === "user" ? styles.user : styles.assistant}><small>{message.role === "user" ? "You" : "QUANTORA assistant"}</small><p>{message.content}</p></div>)}
        {busy && <p className={styles.waiting}>Assistant is thinking…</p>}
      </div><form onSubmit={send} className={styles.form}><label htmlFor={compact ? "assistant-widget-message" : "assistant-message"}>Your message</label><div><textarea id={compact ? "assistant-widget-message" : "assistant-message"} value={draft} onChange={e => setDraft(e.target.value)} maxLength={3000} rows={2} placeholder="Ask about the product…" disabled={busy}/><button type="submit" disabled={busy || !draft.trim()}>Send</button></div>
        {error && <p className={styles.error} role="alert">{error}</p>}<small>The assistant has product context only; it cannot read private documents or live account data.</small></form></div>}
  </div>;
}
