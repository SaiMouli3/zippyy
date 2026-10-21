"use client";

import { Check, ChevronDown, Columns3, X } from "lucide-react";
import { ReactNode, useRef, useState } from "react";

import { cx } from "@/components/platform/ui";
import { useOnClickOutside } from "@/lib/platform/hooks";

/** Popover multi-select whose value is a comma-separated string (matches the API's list filters and the URL). */
export function MultiSelect({ label, value, onChange, options, align = "left" }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => setOpen(false));
  const selected = value ? value.split(",") : [];
  const toggle = (v: string) => onChange((selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]).join(","));
  const summary = selected.length === 0 ? null : selected.length === 1 ? options.find((o) => o.value === selected[0])?.label ?? selected[0] : `${selected.length} selected`;
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="listbox"
        className={cx("inline-flex h-8 max-w-[220px] items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] transition-colors",
          selected.length ? "border-fg-subtle bg-zy-paper-2 text-fg-strong" : "border-line-strong bg-surface text-fg hover:bg-zy-paper")}>
        <span className="text-fg-muted">{label}</span>
        {summary && <span className="truncate font-medium">{summary}</span>}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden />
      </button>
      {open && (
        <div role="listbox" aria-multiselectable aria-label={label}
          className={cx("absolute top-9 z-40 max-h-72 w-60 overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-pop scrollbar-thin", align === "right" ? "right-0" : "left-0")}>
          {options.map((o) => {
            const on = selected.includes(o.value);
            return (
              <button key={o.value} type="button" role="option" aria-selected={on} onClick={() => toggle(o.value)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] text-fg hover:bg-zy-paper">
                <span className={cx("flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border", on ? "border-zy-brand bg-zy-brand text-white" : "border-line-strong")}>
                  {on && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
                </span>
                <span className="truncate">{o.label}</span>
              </button>
            );
          })}
          {selected.length > 0 && (
            <button type="button" onClick={() => onChange("")} className="mt-1 w-full rounded-md border-t border-line px-2 py-1.5 text-left text-2xs font-medium text-fg-muted hover:text-fg-strong">
              Clear {label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function SingleSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  return (
    <label className={cx("inline-flex h-8 items-center gap-1.5 rounded-md border pl-2.5 text-[12.5px]",
      value ? "border-fg-subtle bg-zy-paper-2" : "border-line-strong bg-surface")}>
      <span className="text-fg-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-full max-w-[160px] bg-transparent pr-6 text-[12.5px] font-medium text-fg-strong focus:outline-none">
        <option value="">Any</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function ActiveChips({ chips, onClear }: { chips: { key: string; label: ReactNode; onRemove: () => void }[]; onClear: () => void }) {
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((c) => (
        <span key={c.key} className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-surface py-0.5 pl-2.5 pr-1 text-2xs text-fg">
          {c.label}
          <button onClick={c.onRemove} className="rounded-full p-0.5 text-fg-subtle hover:bg-zy-paper-2 hover:text-fg-strong" aria-label="Remove filter"><X className="h-3 w-3" /></button>
        </span>
      ))}
      <button onClick={onClear} className="text-2xs font-medium text-zy-brand hover:underline">Clear all</button>
    </div>
  );
}

export function ColumnMenu({ columns, hidden, onChange }: {
  columns: { id: string; label: string; required?: boolean }[]; hidden: string[]; onChange: (hidden: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2.5 text-[12.5px] text-fg hover:bg-zy-paper">
        <Columns3 className="h-3.5 w-3.5" aria-hidden /> Columns
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-40 max-h-80 w-56 overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-pop scrollbar-thin">
          {columns.map((c) => {
            const on = !hidden.includes(c.id);
            return (
              <label key={c.id} className={cx("flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px]", c.required ? "text-fg-subtle" : "cursor-pointer text-fg hover:bg-zy-paper")}>
                <input type="checkbox" checked={on} disabled={c.required} className="accent-[#D54029]"
                  onChange={() => onChange(on ? [...hidden, c.id] : hidden.filter((h) => h !== c.id))} />
                {c.label}
              </label>
            );
          })}
          <button onClick={() => onChange([])} className="mt-1 w-full border-t border-line px-2 py-1.5 text-left text-2xs font-medium text-fg-muted hover:text-fg-strong">Show all columns</button>
        </div>
      )}
    </div>
  );
}

export const opts = (m: Record<string, string | { label: string }>) =>
  Object.entries(m).map(([value, v]) => ({ value, label: typeof v === "string" ? v : v.label }));
