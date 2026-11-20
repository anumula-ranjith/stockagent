"use client";

import { MessageCircle, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AssistantChat } from "@/app/assistant/chat";
import styles from "./assistant-widget.module.css";

export function AssistantWidget() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  if (pathname === "/assistant" || pathname === "/datadaily/assistant") return null;
  return <div className={styles.widget}>
    {open && <section className={styles.panel} aria-label="QUANTORA product assistant">
      <div className={styles.heading}><div><strong>Product assistant</strong><small>Private chat · QUANTORA</small></div>
        <button ref={close} type="button" aria-label="Close assistant" onClick={() => { setOpen(false); toggle.current?.focus(); }}><X size={18}/></button></div>
      <AssistantChat compact />
    </section>}
    <button ref={toggle} type="button" className={styles.launcher} aria-label={open ? "Close AI assistant" : "Open AI assistant"}
      aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? <X size={22}/> : <MessageCircle size={22}/>}</button>
  </div>;
}
