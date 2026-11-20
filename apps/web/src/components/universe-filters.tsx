import type { ScreenFilters } from "@/lib/screen-filters";
import styles from "@/app/screener/screener.module.css";

export type UniverseSelection = Pick<ScreenFilters, "index_code" | "cap" | "industry" | "fo_only">;
export type UniverseOptions = {index_options?: Record<string,string>; industries?: string[]};
export function UniverseFilters({draft, set, data}: {
  draft: UniverseSelection; set: (patch: Partial<UniverseSelection>) => void; data?: UniverseOptions;
}) {
  return <section className={styles.universe} aria-label="Universe filters">
      <label className="field">Nifty index
        <select value={draft.index_code} onChange={e => set({index_code: e.target.value})}>
          {Object.entries({NIFTY500: "Nifty 500", ...(draft.index_code !== "NIFTY500" ? {[draft.index_code]: draft.index_code} : {}), ...data?.index_options}).map(([code, label]) =>
            <option key={code} value={code}>{label}</option>)}
        </select>
      </label>
      <label className="field">Market-cap segment
        <select value={draft.cap} onChange={e => set({cap: e.target.value as ScreenFilters["cap"]})}>
          <option value="">All sizes</option>
          <option value="large">Large cap · Nifty 100</option>
          <option value="mid">Mid cap · Midcap 150</option>
          <option value="small">Small cap · Smallcap 250</option>
        </select>
      </label>
      <label className="field">Industry
        <select value={draft.industry} onChange={e => set({industry: e.target.value})}>
          <option value="">All industries</option>
          {Array.from(new Set([...(data?.industries ?? []), ...(draft.industry ? [draft.industry] : [])])).map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
      <label className={styles.eligible}><input type="checkbox" checked={draft.fo_only}
        onChange={e => set({fo_only: e.target.checked})}/>F&amp;O eligible only</label>
    </section>;
}
