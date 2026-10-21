"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { cx } from "@/components/platform/ui";

// Lightweight SVG charts in the Zippyy palette. Every chart carries a visually hidden data table for screen
// readers, honest axes starting at zero, and gaps (not zeros) where data is unavailable.
const BRAND = "#D54029";
const INK = "#2E2E2E";
const GRID = "#EDEDED";

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function dayLabel(d: string): string {
  const dt = new Date(d + "T00:00:00Z");
  return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });
}

/** Measure the rendered width so SVG text stays at its real pixel size instead of scaling with the viewBox. */
function useWidth(initial = 640): [React.RefObject<HTMLElement>, number] {
  const ref = useRef<HTMLElement>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(240, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export type SeriesPoint = { x: string; y: number | null };

export function ColumnChart({ data, label, height = 180, color = BRAND, format = (v: number) => v.toLocaleString("en-IN"), secondary }: {
  data: SeriesPoint[]; label: string; height?: number; color?: string; format?: (v: number) => string;
  secondary?: { data: SeriesPoint[]; label: string; color?: string };
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const max = niceMax(Math.max(1, ...data.map((d) => d.y ?? 0), ...(secondary?.data.map((d) => d.y ?? 0) ?? [0])));
  const [ref, w] = useWidth();
  const h = height, padL = 36, padB = 22, padT = 8;
  const cw = (w - padL) / Math.max(1, data.length);
  const bw = Math.max(3, Math.min(22, cw * (secondary ? 0.36 : 0.6)));
  const y = (v: number) => padT + (h - padT - padB) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const every = Math.ceil(data.length / Math.max(2, Math.floor(w / 80)));
  return (
    <figure ref={ref as React.RefObject<HTMLElement>} className="relative" aria-labelledby={id}>
      <figcaption id={id} className="sr-only">{label}</figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} height={h} width="100%" className="block" role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={w} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#8A8A8A">{format(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * cw + (cw - bw * (secondary ? 2 : 1)) / 2;
          const s = secondary?.data[i];
          return (
            <g key={d.x} onMouseEnter={() => setHover(i)}>
              <rect x={padL + i * cw} y={padT} width={cw} height={h - padT - padB} fill="transparent" />
              {d.y !== null && <rect x={x} y={y(d.y)} width={bw} height={Math.max(0, h - padB - y(d.y))} rx="2" fill={color} opacity={hover === null || hover === i ? 1 : 0.45} />}
              {s && s.y !== null && <rect x={x + bw} y={y(s.y)} width={bw} height={Math.max(0, h - padB - y(s.y))} rx="2" fill={secondary?.color ?? INK} opacity={hover === null || hover === i ? 1 : 0.45} />}
              {i % every === 0 && <text x={padL + i * cw + cw / 2} y={h - 6} textAnchor="middle" fontSize="10" fill="#8A8A8A">{dayLabel(d.x)}</text>}
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute top-0 rounded-md border border-line bg-surface px-2 py-1 text-2xs shadow-pop"
          style={{ left: `${Math.min(80, (hover / data.length) * 100)}%` }}>
          <div className="font-medium text-fg-strong">{dayLabel(data[hover].x)}</div>
          <div><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: color }} />{label}: {data[hover].y === null ? "no data" : format(data[hover].y!)}</div>
          {secondary && <div><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: secondary.color ?? INK }} />{secondary.label}: {secondary.data[hover]?.y === null ? "no data" : format(secondary.data[hover]?.y ?? 0)}</div>}
        </div>
      )}
      <DataTable caption={label} rows={data.map((d, i) => [dayLabel(d.x), d.y === null ? "no data" : format(d.y), ...(secondary ? [secondary.data[i]?.y ?? "no data"] : [])])}
        head={["Day", label, ...(secondary ? [secondary.label] : [])]} />
    </figure>
  );
}

export function LineChart({ data, label, height = 160, format = (v: number) => `${Math.round(v * 100)}%`, max = 1 }: {
  data: SeriesPoint[]; label: string; height?: number; format?: (v: number) => string; max?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [ref, w] = useWidth();
  const h = height, padL = 40, padB = 22, padT = 8;
  const step = (w - padL) / Math.max(1, data.length - 1);
  const y = (v: number) => padT + (h - padT - padB) * (1 - v / max);
  const segments = useMemo(() => {
    const segs: string[] = [];
    let cur = "";
    data.forEach((d, i) => {
      if (d.y === null) { if (cur) segs.push(cur); cur = ""; return; }
      cur += `${cur ? "L" : "M"}${padL + i * step},${y(d.y)} `;
    });
    if (cur) segs.push(cur);
    return segs;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, step]);
  const every = Math.ceil(data.length / Math.max(2, Math.floor(w / 80)));
  return (
    <figure ref={ref as React.RefObject<HTMLElement>} className="relative">
      <svg viewBox={`0 0 ${w} ${h}`} height={h} width="100%" className="block" role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line x1={padL} x2={w} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#8A8A8A">{format(t)}</text>
          </g>
        ))}
        {segments.map((d, i) => <path key={i} d={d} fill="none" stroke={BRAND} strokeWidth="2" />)}
        {data.map((d, i) => (
          <g key={d.x} onMouseEnter={() => setHover(i)}>
            <rect x={padL + i * step - step / 2} y={padT} width={step} height={h - padB - padT} fill="transparent" />
            {d.y !== null && <circle cx={padL + i * step} cy={y(d.y)} r={hover === i ? 4 : 2.5} fill={BRAND} />}
            {i % every === 0 && <text x={padL + i * step} y={h - 6} textAnchor="middle" fontSize="10" fill="#8A8A8A">{dayLabel(d.x)}</text>}
          </g>
        ))}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-0 rounded-md border border-line bg-surface px-2 py-1 text-2xs shadow-pop" style={{ left: `${Math.min(80, (hover / data.length) * 100)}%` }}>
          <span className="font-medium text-fg-strong">{dayLabel(data[hover].x)}</span> · {data[hover].y === null ? "no closed cases" : format(data[hover].y!)}
        </div>
      )}
      <DataTable caption={label} head={["Day", label]} rows={data.map((d) => [dayLabel(d.x), d.y === null ? "no data" : format(d.y)])} />
    </figure>
  );
}

export function HBars({ items, total, format = (v: number) => v.toLocaleString("en-IN"), color = BRAND, emptyText = "No data in this period" }: {
  items: { label: string; value: number; href?: string; sub?: string }[]; total?: number; format?: (v: number) => string; color?: string; emptyText?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const sum = total ?? items.reduce((a, b) => a + b.value, 0);
  if (!items.length) return <p className="py-6 text-center text-[12.5px] text-fg-muted">{emptyText}</p>;
  return (
    <ul className="space-y-2">
      {items.map((it) => {
        const row = (
          <div className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
            <span className="truncate text-[12.5px] text-fg">{it.label}</span>
            <span className="h-2 overflow-hidden rounded-full bg-zy-paper-2">
              <span className="block h-full rounded-full" style={{ width: `${(it.value / max) * 100}%`, background: color }} />
            </span>
            <span className="num w-20 text-right text-[12.5px] text-fg-strong">{format(it.value)}{sum ? <span className="ml-1 text-fg-subtle">{Math.round((it.value / sum) * 100)}%</span> : null}</span>
          </div>
        );
        return <li key={it.label}>{it.href ? <Link href={it.href} className="block rounded px-1 py-0.5 hover:bg-zy-paper">{row}</Link> : <div className="px-1 py-0.5">{row}</div>}</li>;
      })}
    </ul>
  );
}

export function StackedBars({ rows, keys }: {
  rows: { label: string; values: Record<string, number>; href?: string }[]; keys: { key: string; label: string; color: string }[];
}) {
  if (!rows.length) return <p className="py-6 text-center text-[12.5px] text-fg-muted">No data in this period</p>;
  return (
    <div>
      <ul className="space-y-2.5">
        {rows.map((r) => {
          const total = keys.reduce((a, k) => a + (r.values[k.key] ?? 0), 0);
          return (
            <li key={r.label} className="grid grid-cols-[minmax(0,8rem)_1fr_3rem] items-center gap-3">
              <span className="truncate text-[12.5px] text-fg">{r.href ? <Link href={r.href} className="hover:underline">{r.label}</Link> : r.label}</span>
              <span className="flex h-3 overflow-hidden rounded bg-zy-paper-2" role="img" aria-label={`${r.label}: ${keys.map((k) => `${k.label} ${r.values[k.key] ?? 0}`).join(", ")}`}>
                {keys.map((k) => total ? <span key={k.key} style={{ width: `${((r.values[k.key] ?? 0) / total) * 100}%`, background: k.color }} title={`${k.label}: ${r.values[k.key] ?? 0}`} /> : null)}
              </span>
              <span className="num text-right text-[12.5px] text-fg-muted">{total}</span>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex flex-wrap gap-3">
        {keys.map((k) => <span key={k.key} className="inline-flex items-center gap-1.5 text-2xs text-fg-muted"><span className="h-2 w-2 rounded-sm" style={{ background: k.color }} />{k.label}</span>)}
      </div>
    </div>
  );
}

function DataTable({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className={cx("flex flex-wrap gap-3")}>
      {items.map((i) => <span key={i.label} className="inline-flex items-center gap-1.5 text-2xs text-fg-muted"><span className="h-2 w-2 rounded-sm" style={{ background: i.color }} />{i.label}</span>)}
    </div>
  );
}

export const CHART = { BRAND, INK, OK: "#1F7A4D", WARN: "#C98A1B", MUTED: "#C9C9C9", INFO: "#0B63D1" };
