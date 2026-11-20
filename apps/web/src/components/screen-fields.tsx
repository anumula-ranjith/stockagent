import { candleLabels, validDistance, type ScreenFilters } from "@/lib/screen-filters";

type Props = {screen: ScreenFilters; change: (patch: Partial<ScreenFilters>) => void};

export function RangeFields({screen, change}: Props) {
  return <>
    <label className="field">Reference level
      <select value={screen.reference} onChange={e => change({reference: e.target.value as ScreenFilters["reference"]})}>
        <option value="high">52-week high</option><option value="low">52-week low</option>
      </select>
    </label>
    <label className="field">Distance from level (%)
      <input type="text" inputMode="text" placeholder="e.g. −5 or +5" maxLength={40}
        ref={input => { input?.setCustomValidity(validDistance(screen.distance) ? "" : "Enter a percentage between -100 and +10000."); }}
        value={screen.distance} onChange={e => change({distance: e.target.value.replace(/−/g, "-").trim()})}/>
    </label>
    <p className="subtle">+5 matches prices up to 5% above the level. −5 matches up to 5% below. Enter 0 for the exact level or leave blank for any distance.</p>
  </>;
}

export function CandleField({screen, change}: Props) {
  return <label className="field">Candle color change
    <select value={screen.heikin_ashi_rule}
      onChange={e => change({heikin_ashi_rule: e.target.value as ScreenFilters["heikin_ashi_rule"]})}>
      {Object.entries(candleLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}
    </select>
  </label>;
}
