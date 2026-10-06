import { useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, Loader2, XCircle } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { pretty } from '@/lib/format'

type Tone = 'neutral' | 'info' | 'ok' | 'warn' | 'bad' | 'violet' | 'brand'
const toneCls: Record<Tone, string> = {
  neutral: 'bg-surface2 text-ink2 border-line',
  info: 'bg-infosoft text-info border-transparent',
  ok: 'bg-oksoft text-ok border-transparent',
  warn: 'bg-warnsoft text-warn border-transparent',
  bad: 'bg-badsoft text-bad border-transparent',
  violet: 'bg-violetsoft text-violet border-transparent',
  brand: 'bg-brandsoft text-brand border-transparent',
}

export function Badge({ tone = 'neutral', children, dot, title }: { tone?: Tone; children: ReactNode; dot?: boolean; title?: string }) {
  return (
    <span title={title} className={clsx('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap', toneCls[tone])}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  )
}

const statusTone: Record<string, Tone> = {
  ORDER_CREATED: 'neutral', RATES_FETCHED: 'neutral', CARRIER_SELECTED: 'info', SHIPMENT_CREATED: 'info', PICKED_UP: 'info', IN_TRANSIT: 'info',
  OUT_FOR_DELIVERY: 'violet', DELIVERED: 'ok', DELIVERY_FAILED: 'bad', RTO: 'warn',
  OPENED: 'bad', BUYER_CONTACT_PENDING: 'warn', BUYER_RESPONDED: 'info', INTENT_EXTRACTED: 'info', AWAITING_APPROVAL: 'warn', ACTION_PENDING: 'info',
  ACTION_SUBMITTED: 'violet', CARRIER_ACCEPTED: 'ok', REATTEMPT_SCHEDULED: 'ok', RESOLVED: 'ok', ESCALATED: 'bad', RTO_INITIATED: 'warn', CLOSED: 'neutral',
  PENDING: 'warn', APPROVED: 'ok', REJECTED: 'bad', EXPIRED: 'neutral', ACCEPTED: 'ok', FAILED: 'bad',
}
export function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return <Badge>—</Badge>
  return <Badge tone={statusTone[status] ?? 'neutral'} dot>{pretty(status)}</Badge>
}

export function Card({ title, actions, children, className, pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx('rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,0.04)]', className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, actions, crumbs }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; crumbs?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        {crumbs && <div className="mb-1 text-xs text-muted">{crumbs}</div>}
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink2">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  )
}

type BtnVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export function Button({ variant = 'secondary', loading, className, children, disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; loading?: boolean }) {
  const v: Record<BtnVariant, string> = {
    primary: 'bg-brand text-white hover:brightness-110 border-transparent',
    secondary: 'bg-surface text-ink border-line hover:bg-surface2',
    danger: 'bg-bad text-white border-transparent hover:brightness-110',
    ghost: 'bg-transparent text-ink2 border-transparent hover:bg-surface2',
  }
  return (
    <button {...rest} disabled={disabled || loading}
      className={clsx('inline-flex h-9 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50', v[variant], className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

export function Field({ label, error, hint, children, className }: { label: string; error?: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={clsx('block', className)}>
      <span className="mb-1 block text-xs font-medium text-ink2">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-muted">{hint}</span>}
      {error && <span role="alert" className="mt-1 block text-xs text-bad">{error}</span>}
    </label>
  )
}

export const inputCls = 'h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink placeholder:text-muted focus:border-brand focus:outline-none'

export function Banner({ tone = 'info', title, children }: { tone?: 'info' | 'ok' | 'warn' | 'bad'; title?: ReactNode; children?: ReactNode }) {
  const Icon = { info: Info, ok: CheckCircle2, warn: AlertTriangle, bad: XCircle }[tone]
  const cls = { info: 'bg-infosoft text-info', ok: 'bg-oksoft text-ok', warn: 'bg-warnsoft text-warn', bad: 'bg-badsoft text-bad' }[tone]
  return (
    <div role={tone === 'bad' ? 'alert' : 'status'} className={clsx('flex gap-3 rounded-lg px-3 py-2.5 text-sm', cls)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className="text-ink2">{children}</div>}
      </div>
    </div>
  )
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null
  const e = error as ApiError
  return (
    <Banner tone="bad" title={e instanceof ApiError ? `${e.code}` : 'Something went wrong'}>
      {e.message}
      {e instanceof ApiError && e.requestId && <span className="ml-2 font-mono text-xs text-muted">request {e.requestId.slice(0, 8)}</span>}
    </Banner>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}</div>
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className="text-sm font-medium text-ink">{title}</div>
      {hint && <div className="max-w-md text-sm text-muted">{hint}</div>}
      {action}
    </div>
  )
}

export function KV({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={clsx('mt-0.5 break-words text-sm text-ink', mono && 'font-mono text-[13px]')}>{children}</dd>
    </div>
  )
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('overflow-x-auto', className)}><table className="w-full border-collapse text-sm">{children}</table></div>
}
export const Th = ({ children, right, className }: { children?: ReactNode; right?: boolean; className?: string }) => (
  <th className={clsx('whitespace-nowrap border-b border-line bg-surface2 px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted first:rounded-tl-lg last:rounded-tr-lg', right && 'text-right', className)}>{children}</th>
)
export const Td = ({ children, right, className, mono }: { children?: ReactNode; right?: boolean; className?: string; mono?: boolean }) => (
  <td className={clsx('border-b border-line px-3 py-2.5 align-middle text-ink', right && 'text-right tabular', mono && 'font-mono text-[13px]', className)}>{children}</td>
)

export function JsonDetails({ data, label = 'Details' }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false)
  if (data === undefined || data === null) return null
  return (
    <div className="mt-1">
      <button onClick={() => setOpen(o => !o)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink">
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} {label}
      </button>
      {open && <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-surface2 p-2.5 font-mono text-xs text-ink2">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: Array<{ id: T; label: ReactNode }>; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 border-b border-line">
      {tabs.map(t => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={clsx('-mb-px border-b-2 px-3 py-2 text-sm font-medium', value === t.id ? 'border-brand text-ink' : 'border-transparent text-muted hover:text-ink')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}
