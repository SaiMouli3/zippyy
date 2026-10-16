"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Info, Loader2, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import {
  ButtonHTMLAttributes, forwardRef, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes,
  useEffect, useId, useRef, useState,
} from "react";

import { absolute, relative } from "@/lib/platform/format";
import { useNow } from "@/lib/platform/hooks";
import { LANG, Tone } from "@/lib/platform/labels";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ------------------------------------------------------------------ buttons
type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-zy-brand text-white hover:bg-zy-brand-hover border border-zy-brand",
  secondary: "bg-surface text-fg-strong border border-line-strong hover:border-fg-subtle hover:bg-zy-paper",
  ghost: "text-fg hover:bg-zy-paper-2 border border-transparent",
  danger: "bg-danger text-white hover:opacity-90 border border-danger",
  dark: "bg-zy-ink text-white hover:bg-zy-ink-3 border border-zy-ink",
};

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode;
}>(function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]",
        VARIANTS[variant], className,
      )}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function ButtonLink({ href, children, variant = "secondary", size = "md", icon }: {
  href: string; children: ReactNode; variant?: Variant; size?: "sm" | "md"; icon?: ReactNode;
}) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors",
      size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]", VARIANTS[variant])}>
      {icon}{children}
    </Link>
  );
}

// ------------------------------------------------------------------ badges
const TONES: Record<Tone, string> = {
  neutral: "bg-zy-paper-2 text-fg border-line",
  ok: "bg-ok-soft text-ok border-[#CDE7D9]",
  warn: "bg-warn-soft text-warn border-[#F6DDB5]",
  danger: "bg-danger-soft text-danger border-[#F6C9C4]",
  info: "bg-info-soft text-info border-[#C9DDFA]",
  brand: "bg-zy-brand-soft text-zy-brand border-[#F3C7BE]",
  muted: "bg-surface text-fg-muted border-line",
};
const DOTS: Record<Tone, string> = {
  neutral: "bg-fg-subtle", ok: "bg-ok", warn: "bg-warn", danger: "bg-danger", info: "bg-info", brand: "bg-zy-brand", muted: "bg-line-strong",
};

export function Badge({ tone = "neutral", children, hint, dot = true, className }: {
  tone?: Tone; children: ReactNode; hint?: string; dot?: boolean; className?: string;
}) {
  const badge = (
    <span className={cx("inline-flex max-w-full items-center gap-1.5 truncate rounded border px-1.5 py-px text-2xs font-medium", TONES[tone], className)}>
      {dot && <span aria-hidden className={cx("h-1.5 w-1.5 shrink-0 rounded-full", DOTS[tone])} />}
      <span className="truncate">{children}</span>
    </span>
  );
  return hint ? <Tooltip text={hint}>{badge}</Tooltip> : badge;
}

export function StatusBadge({ map, value }: { map: Record<string, { label: string; tone: Tone; hint?: string }>; value: string | null | undefined }) {
  if (!value) return <span className="text-fg-subtle">—</span>;
  const e = map[value] ?? { label: value.replace(/_/g, " "), tone: "neutral" as Tone };
  return <Badge tone={e.tone} hint={e.hint}>{e.label}</Badge>;
}

export function LangTag({ code, source, confirmed }: { code: string | null | undefined; source?: string | null; confirmed?: boolean }) {
  if (!code) return <span className="text-fg-subtle">—</span>;
  return (
    <Tooltip text={`${LANG[code] ?? code}${source ? ` · ${source.replace(/_/g, " ")}` : ""}${confirmed === false ? " (predicted, not confirmed)" : ""}`}>
      <span className={cx("inline-flex items-center rounded border px-1 font-mono text-2xs uppercase",
        confirmed ? "border-fg-subtle text-fg-strong" : "border-dashed border-line-strong text-fg-muted")}>{code}</span>
    </Tooltip>
  );
}

// ------------------------------------------------------------------ tooltip
export function Tooltip({ text, children, side = "top" }: { text: string; children: ReactNode; side?: "top" | "bottom" }) {
  const id = useId();
  return (
    <span className="group/tt relative inline-flex max-w-full" aria-describedby={id}>
      {children}
      <span id={id} role="tooltip"
        className={cx("pointer-events-none absolute left-1/2 z-50 hidden w-max max-w-[260px] -translate-x-1/2 rounded-md bg-zy-ink px-2 py-1 text-2xs font-normal leading-4 text-white shadow-pop group-focus-within/tt:block group-hover/tt:block",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5")}>
        {text}
      </span>
    </span>
  );
}

// ------------------------------------------------------------------ panels
export function Panel({ children, className, as: As = "section", ...rest }: { children: ReactNode; className?: string; as?: "section" | "div"; id?: string; "aria-label"?: string }) {
  return <As {...rest} className={cx("rounded-[10px] border border-line bg-surface shadow-panel", className)}>{children}</As>;
}

export function PanelHeader({ title, subtitle, actions, className }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5", className)}>
      <div className="min-w-0">
        <h2 className="font-heading text-[14px] font-bold leading-5 text-fg-strong">{title}</h2>
        {subtitle && <p className="text-2xs text-fg-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions, meta }: { title: string; description?: ReactNode; actions?: ReactNode; meta?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-heading text-[20px] font-bold leading-7 tracking-[-0.01em] text-fg-strong">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-[13px] text-fg-muted">{description}</p>}
        {meta && <div className="mt-1.5 flex flex-wrap items-center gap-2 text-2xs text-fg-muted">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function KeyValue({ items, cols = 2 }: { items: { k: ReactNode; v: ReactNode; hint?: string }[]; cols?: 1 | 2 | 3 | 4 }) {
  const grid = { 1: "grid-cols-1", 2: "grid-cols-1 sm:grid-cols-2", 3: "grid-cols-2 lg:grid-cols-3", 4: "grid-cols-2 lg:grid-cols-4" }[cols];
  return (
    <dl className={cx("grid gap-x-6 gap-y-2.5", grid)}>
      {items.map((it, i) => (
        <div key={i} className="min-w-0">
          <dt className="text-2xs font-medium uppercase tracking-wide text-fg-subtle">{it.k}</dt>
          <dd className="mt-0.5 truncate text-[13px] text-fg-strong">{it.v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ states
export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-3", className)} aria-hidden />;
}

export function SkeletonRows({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-line" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4 px-4 py-3">
          {Array.from({ length: cols }).map((__, c) => <Skeleton key={c} className={cx("h-3", c === 0 ? "w-24" : "flex-1")} />)}
        </div>
      ))}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 h-9 w-9 rounded-full border border-dashed border-line-strong" aria-hidden />
      <p className="font-heading text-[14px] font-bold text-fg-strong">{title}</p>
      {children && <p className="mt-1 max-w-md text-[13px] text-fg-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const e = error as { message?: string; status?: number; requestId?: string; code?: string };
  return (
    <div role="alert" className={cx("flex items-start gap-3 rounded-md border border-[#F6C9C4] bg-danger-soft text-danger", compact ? "m-3 p-2.5" : "m-4 p-3.5")}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-[13px]">
        <p className="font-medium">{e?.status === 403 ? "You don't have access to this." : e?.message || "Something went wrong."}</p>
        {e?.requestId && <p className="mt-0.5 text-2xs opacity-80">Reference {e.requestId}</p>}
      </div>
      {onRetry && <Button size="sm" variant="secondary" onClick={onRetry} icon={<RefreshCw className="h-3 w-3" />}>Retry</Button>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div className={cx("flex items-start gap-2 rounded-md border px-3 py-2 text-[12.5px]",
      tone === "info" ? "border-[#C9DDFA] bg-info-soft text-[#0A4FA6]" : "border-[#F6DDB5] bg-warn-soft text-warn")}>
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><div>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ time
export function Timestamp({ iso, mode = "relative" }: { iso: string | null | undefined; mode?: "relative" | "absolute" }) {
  const now = useNow();
  if (!iso) return <span className="text-fg-subtle">—</span>;
  return (
    <Tooltip text={absolute(iso, true)}>
      <time dateTime={iso} className="whitespace-nowrap">{mode === "relative" ? relative(iso, now) : absolute(iso)}</time>
    </Tooltip>
  );
}

function span(hoursAbs: number): string {
  if (hoursAbs < 1) return `${Math.max(1, Math.round(hoursAbs * 60))}m`;
  if (hoursAbs < 48) return `${Math.round(hoursAbs)}h`;
  return `${Math.round(hoursAbs / 24)}d`;
}

export function SlaCell({ iso, closed, compact }: { iso: string | null | undefined; closed?: boolean; compact?: boolean }) {
  const now = useNow();
  if (!iso) return <span className="text-fg-subtle">—</span>;
  const hours = (new Date(iso).getTime() - now) / 3600000;
  const tone: Tone = closed ? "muted" : hours < 0 ? "danger" : hours < 4 ? "warn" : "neutral";
  const label = closed ? (compact ? "Closed" : absolute(iso))
    : hours < 0 ? (compact ? `${span(-hours)} over` : `Breached ${span(-hours)} ago`)
      : compact ? `${span(hours)} left` : `Due in ${span(hours)}`;
  return (
    <Tooltip text={`SLA deadline ${absolute(iso)}`}>
      <span className={cx("inline-flex items-center gap-1 whitespace-nowrap text-[12.5px]",
        tone === "danger" ? "font-semibold text-danger" : tone === "warn" ? "font-medium text-warn" : "text-fg")}>
        {tone === "danger" && <AlertTriangle className="h-3 w-3" aria-hidden />}
        {label}
      </span>
    </Tooltip>
  );
}

export function Freshness({ at, fetching, onRefresh }: { at: string | number | null | undefined; fetching?: boolean; onRefresh?: () => void }) {
  const now = useNow(10000);
  const iso = typeof at === "number" ? new Date(at).toISOString() : at;
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs text-fg-muted">
      {fetching ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {iso ? <>Updated {relative(iso, now)}</> : "Not loaded"}
      {onRefresh && (
        <button onClick={onRefresh} className="rounded p-0.5 hover:bg-zy-paper-2" aria-label="Refresh now">
          <RefreshCw className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}

// ------------------------------------------------------------------ form controls
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} {...rest} className={cx("h-8 w-full rounded-md border border-line-strong bg-surface px-2.5 text-[13px] text-fg-strong placeholder:text-fg-subtle focus:border-fg-subtle focus:outline-none", className)} />;
});

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx("w-full rounded-md border border-line-strong bg-surface px-2.5 py-2 text-[13px] text-fg-strong placeholder:text-fg-subtle focus:border-fg-subtle focus:outline-none", props.className)} />;
}

export function Select({ label, options, className, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string; options: { value: string; label: string }[];
}) {
  const id = useId();
  return (
    <div className={cx("min-w-0", className)}>
      {label && <label htmlFor={id} className="sr-only">{label}</label>}
      <select id={id} {...rest} className="h-8 w-full truncate rounded-md border border-line-strong bg-surface pl-2 pr-7 text-[13px] text-fg-strong focus:border-fg-subtle focus:outline-none">
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export function Field({ label, hint, children, error }: { label: string; hint?: ReactNode; children: ReactNode; error?: string }) {
  return (
    <label className="block">
      <span className="text-[12px] font-medium text-fg-strong">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && !error && <span className="mt-1 block text-2xs text-fg-muted">{hint}</span>}
      {error && <span className="mt-1 block text-2xs text-danger">{error}</span>}
    </label>
  );
}

// ------------------------------------------------------------------ tabs
export function Tabs<T extends string>({ tabs, value, onChange, className }: {
  tabs: { id: T; label: ReactNode; count?: number | null }[]; value: T; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cx("flex gap-1 overflow-x-auto border-b border-line scrollbar-thin", className)}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("relative -mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
            value === t.id ? "border-zy-brand text-fg-strong" : "border-transparent text-fg-muted hover:text-fg-strong")}>
          {t.label}
          {t.count !== undefined && t.count !== null && <span className="rounded bg-zy-paper-2 px-1 text-2xs text-fg-muted">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ dialog
export function Dialog({ open, onClose, title, children, footer, width = "max-w-lg" }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; width?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const node = ref.current;
    node?.querySelector<HTMLElement>("input, textarea, select, button:not([data-close])")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && node) {
        const f = Array.from(node.querySelectorAll<HTMLElement>("button, [href], input, select, textarea")).filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-zy-ink/40 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={cx("w-full animate-fade-in rounded-t-xl bg-surface shadow-pop sm:rounded-xl", width)}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-heading text-[15px] font-bold text-fg-strong">{title}</h2>
          <button data-close onClick={onClose} className="rounded p-1 text-fg-muted hover:bg-zy-paper-2" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-4 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/** Consequential actions require an explicit, typed reason and a confirmation tick. */
export function ConfirmDialog({ open, onClose, title, description, confirmLabel, tone = "primary", onConfirm, busy, error, requireReason = true, children,
  ackText = "I understand this is recorded against my name. Approving sends a request; it does not mean the carrier has done it.", canConfirm = true }: {
  open: boolean; onClose: () => void; title: string; description: ReactNode; confirmLabel: string; tone?: Variant;
  onConfirm: (reason: string) => void; busy?: boolean; error?: unknown; requireReason?: boolean; children?: ReactNode; ackText?: string; canConfirm?: boolean;
}) {
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  useEffect(() => { if (open) { setReason(""); setAck(false); } }, [open]);
  const ok = (!requireReason || reason.trim().length >= 5) && ack && canConfirm;
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant={tone} disabled={!ok} loading={busy} onClick={() => onConfirm(reason.trim())}>{confirmLabel}</Button>
      </>}>
      <div className="space-y-3 text-[13px] text-fg">
        <div>{description}</div>
        {children}
        {requireReason && (
          <Field label="Reason (recorded in the audit log)" hint="At least 5 characters.">
            <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          </Field>
        )}
        <label className="flex items-start gap-2 text-[12.5px]">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 accent-[#D54029]" />
          <span>{ackText}</span>
        </label>
        {error ? <ErrorBox error={error} compact /> : null}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ pagination
export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2 border-t border-line px-4 py-2 text-[12.5px] text-fg-muted">
      <span className="num">{from.toLocaleString("en-IN")}–{to.toLocaleString("en-IN")} of {total.toLocaleString("en-IN")}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-3.5 w-3.5" /></Button>
        <span className="num px-1">Page {page} of {pages}</span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight className="h-3.5 w-3.5" /></Button>
      </div>
    </nav>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[12px] text-fg-strong", className)}>{children}</span>;
}
