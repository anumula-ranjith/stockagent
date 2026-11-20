import type { ScreenFilters } from "@/lib/screen-filters";
import { ChartNoAxesColumnIncreasing, Factory, Layers3 } from "lucide-react";
import { UniverseSelect } from "./universe-select";
import styles from "@/app/screener/screener.module.css";

export type UniverseSelection = Pick<ScreenFilters, "index_code" | "cap" | "industry" | "fo_only">;
export type UniverseOptions = {index_options?: Record<string,string>; industries?: string[]};
const sectors = new Set(["NIFTYBANK", "NIFTYIT", "NIFTYAUTO", "NIFTYPHARMA"]);
const broad = new Set(["NIFTY500","NIFTY50","NIFTYNEXT50","NIFTY100","NIFTY200","NIFTYMIDCAP150","NIFTYSMALLCAP250"]);
const caps = [
  {value: "", label: "All sizes"}, {value: "large", label: "Large cap", detail: "Nifty 100"},
  {value: "mid", label: "Mid cap", detail: "Midcap 150"}, {value: "small", label: "Small cap", detail: "Smallcap 250"},
];
export function UniverseFilters({draft, set, data}: {
  draft: UniverseSelection; set: (patch: Partial<UniverseSelection>) => void; data?: UniverseOptions;
}) {
  const indexNames = {NIFTY500: "Nifty 500", ...data?.index_options};
  const indices = Object.entries(indexNames).map(([value, label]) => ({value, label,
    group: broad.has(value) ? "Broad market" : sectors.has(value) ? "Sector indices" : "Other indices"}));
  if (!indices.some(option => option.value === draft.index_code))
    indices.push({value: draft.index_code, label: draft.index_code, group: "Other indices"});
  const industries = Array.from(new Set([...(data?.industries ?? []), draft.industry])).filter(Boolean);
  return <section className={styles.universe} aria-label="Universe filters">
      <UniverseSelect label="Nifty index" icon={Layers3} placeholder="Find an index…" value={draft.index_code}
        options={indices} onChange={index_code => set({index_code})}/>
      <UniverseSelect label="Market-cap segment" icon={ChartNoAxesColumnIncreasing} placeholder="Find a segment…"
        value={draft.cap} options={caps} onChange={cap => set({cap: cap as UniverseSelection["cap"]})}/>
      <UniverseSelect label="Industry" icon={Factory} placeholder="Find an industry…" value={draft.industry}
        options={[{value:"", label:"All industries"}, ...industries.map(value => ({value, label:value}))]}
        onChange={industry => set({industry})}/>
      <label className={styles.eligible}><input type="checkbox" checked={draft.fo_only}
        onChange={e => set({fo_only: e.target.checked})}/>F&amp;O eligible only</label>
    </section>;
}
