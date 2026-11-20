"use client";

import { useEffect, useState, type MouseEvent } from "react";
import { ArrowLeft } from "lucide-react";

// Only the first-party stock links opt in to keeping a reference to their results tab.
function openerUrl(): URL | undefined {
  try {
    if (window.opener && !window.opener.closed) {
      const url = new URL(window.opener.location.href);
      if (url.origin === location.origin) return url;
    }
  } catch { /* The results tab may have navigated to another origin. */ }
}

export function StockReturnLink({fallback = "/stocks"}: {fallback?: string}) {
  const [source, setSource] = useState<string>();
  useEffect(() => {
    const referrer = document.referrer ? new URL(document.referrer) : undefined;
    if (referrer?.origin !== location.origin) return;
    const opener = openerUrl();
    // Referrer URLs omit fragments. Keep the exact section if the opener is still there.
    setSource(opener && opener.pathname === referrer.pathname && opener.search === referrer.search
      ? opener.href : referrer.href);
  }, []);

  function returnToResults(event: MouseEvent<HTMLAnchorElement>) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (source && openerUrl()?.href === source) {
      event.preventDefault();
      window.opener.focus();
      window.close();
      // Some browsers disallow closing a tab opened through their context menu.
      window.setTimeout(() => window.location.assign(source), 100);
    }
  }

  return <a href={source ?? fallback} className="text-link mb-4" onClick={returnToResults}>
    <ArrowLeft size={16} aria-hidden="true"/>{source ? "Back to results" : "Back to stocks"}
  </a>;
}
