"use client";

import { Download, Mail, Settings, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, apiResponse } from "@/lib/api";
import { screenRequest, type ScreenFilters } from "@/lib/screen-filters";
import styles from "./screener.module.css";

type Selection = {filters: ScreenFilters; version: string; tickers: string[]; asof: string | null};

export function ResultSettings({selection, updating}: {selection: Selection; updating: boolean}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [snapshot, setSnapshot] = useState<Selection | null>(null);
  const [recipient, setRecipient] = useState("");
  const [busy, setBusy] = useState<"download" | "email" | null>(null);
  const [message, setMessage] = useState("");

  async function deliver(action: "download" | "email") {
    if (!snapshot || busy) return;
    setBusy(action);
    setMessage("");
    const body = {screen: screenRequest(snapshot.filters), export_version: snapshot.version, tickers: snapshot.tickers};
    try {
      if (action === "email") {
        const address = recipient.trim();
        await api("/screener/email", {method: "POST", body: JSON.stringify({...body, recipient: address})});
        setMessage("Email sent to " + address + ".");
      } else {
        const response = await apiResponse("/screener/export", {method: "POST", body: JSON.stringify(body)});
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = "screener-" + snapshot.asof + ".xlsx";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setMessage("Excel download started.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The request failed. Please try again.");
    } finally {
      setBusy(null);
    }
  }
  return <>
    <Button type="button" variant="secondary" aria-haspopup="dialog" disabled={updating || !selection.tickers.length || !!busy}
      onClick={() => {setSnapshot(selection); setMessage(""); dialog.current?.showModal();}}>
      <Settings size={16}/> Settings
    </Button>
    <dialog ref={dialog} className={styles.exportDialog} aria-labelledby="result-settings-title">
      <div className={styles.dialogHeading}><h2 id="result-settings-title">Result settings</h2>
        <button type="button" className="icon-button" aria-label="Close result settings" onClick={() => dialog.current?.close()}><X size={18}/></button></div>
      <p>{snapshot?.tickers.length ?? 0} matching stocks · Excel workbook (.xlsx)</p>
      <Button variant="secondary" type="button" disabled={!!busy} onClick={() => void deliver("download")}>
        <Download size={16}/>{busy === "download" ? "Preparing workbook…" : "Download Excel"}
      </Button>
      <form onSubmit={e => {e.preventDefault(); void deliver("email");}}>
        <label className="field">Recipient email<input type="email" required maxLength={254} value={recipient}
          disabled={!!busy} onChange={e => {setRecipient(e.target.value); setMessage("");}}/></label>
        <Button type="submit" disabled={!!busy || !recipient.trim()}><Mail size={16}/>{busy === "email" ? "Sending…" : "Send Excel by email"}</Button>
      </form>
      <div role="status" aria-live="polite">{message}</div>
    </dialog>
  </>;
}
