"use client";

import { Check, ChevronDown, type LucideIcon } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import s from "./universe-select.module.css";

export type FilterOption = {value: string; label: string; detail?: string; group?: string};

export function UniverseSelect({label, icon: Icon, placeholder, value, options, onChange}: {
  label: string; icon: LucideIcon; placeholder: string; value: string; options: FilterOption[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [placement, setPlacement] = useState({above: false, height: 320});
  const selected = options.find(option => option.value === value);
  const term = query.trim().toLowerCase();
  const matches = options.filter(option => [option.label, option.detail, option.value]
    .some(text => text?.toLowerCase().includes(term)));
  const active = Math.min(highlight, matches.length - 1);
  const optionId = (index: number) => id + "-option-" + index;

  function show() {
    setQuery("");
    setHighlight(Math.max(0, options.findIndex(option => option.value === value)));
    setOpen(true);
  }
  function choose(option: FilterOption) {
    onChange(option.value);
    setOpen(false);
    input.current?.focus({preventScroll: true});
  }
  useEffect(() => {
    if (!open || !root.current) return;
    const element = root.current;
    function position() {
      const rect = element.getBoundingClientRect();
      const below = window.innerHeight - rect.bottom - 12;
      const above = below < 210 && rect.top > below;
      setPlacement({above, height: Math.min(320, Math.max(80, above ? rect.top - 12 : below))});
    }
    function dismiss(event: PointerEvent) {
      if (!element.contains(event.target as Node)) setOpen(false);
    }
    position();
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open]);
  useEffect(() => {
    if (!open || active < 0) return;
    const option = document.getElementById(id + "-option-" + active);
    const list = option?.parentElement;
    if (!option || !list) return;
    if (option.offsetTop < list.scrollTop) list.scrollTop = option.offsetTop;
    else if (option.offsetTop + option.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = option.offsetTop + option.offsetHeight - list.clientHeight;
  }, [open, active, id, query, placement.height]);

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) show();
      else setHighlight(Math.max(0, Math.min(matches.length - 1, active + (event.key === "ArrowDown" ? 1 : -1))));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (!open) show();
      else if (matches[active]) choose(matches[active]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    } else if (!open && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      setQuery(event.key);
      setHighlight(0);
      setOpen(true);
    }
  }

  return <div className={s.field}>
    <label id={id + "-label"} htmlFor={id}>{label}</label>
    <div ref={root} className={s.anchor}>
      <div className={s.control} data-open={open}>
        <Icon size={17} aria-hidden="true" className={s.icon}/>
        <input ref={input} id={id} role="combobox" autoComplete="off" spellCheck={false}
          aria-autocomplete="list" aria-expanded={open} aria-controls={open ? id + "-list" : undefined}
          aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
          value={open ? query : selected?.label ?? value} placeholder={placeholder}
          onClick={() => { if (!open) show(); }} onFocus={e => e.target.select()} onBlur={() => setOpen(false)}
          onChange={e => { setQuery(e.target.value); setHighlight(0); setOpen(true); }} onKeyDown={keyDown}/>
        <button type="button" tabIndex={-1} aria-label={`${open ? "Close" : "Open"} ${label}`}
          onMouseDown={e => e.preventDefault()} onClick={() => {
            input.current?.focus(); if (open) setOpen(false); else show();
          }}><ChevronDown size={16} aria-hidden="true"/></button>
      </div>
      {open && <div className={s.menu} data-above={placement.above} style={{maxHeight: placement.height}}
        id={id + "-list"} role="listbox" aria-labelledby={id + "-label"}>
        {matches.map((option, index) => <Fragment key={option.value}>
          {option.group && option.group !== matches[index - 1]?.group && <span className={s.group} aria-hidden="true">{option.group}</span>}
          <div className={s.row} role="option" id={optionId(index)} aria-selected={option.value === value}
            data-active={index === active} onMouseDown={e => e.preventDefault()} onClick={() => choose(option)}>
            <span>{option.label}</span>{option.detail && <small>{option.detail}</small>}
            {option.value === value && <Check size={16} aria-hidden="true"/>}
          </div>
        </Fragment>)}
        {!matches.length && <div className={s.empty} role="presentation">No matches</div>}
      </div>}
    </div>
  </div>;
}
