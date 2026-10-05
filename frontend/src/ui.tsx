import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export const inr = (n: number) => `₹${n.toFixed(2)}`
export const nice = (s: string) => (s === 'NDR' ? 'NDR' : s.split('_').map((w) => w[0] + w.slice(1).toLowerCase()).join(' '))
export const CARRIER_NAMES: Record<string, string> = { FASTSHIP: 'FastShip', QUICKEXPRESS: 'QuickExpress', RELIABLECOURIER: 'ReliableCourier' }
export const CARRIER_SLUG: Record<string, string> = { FASTSHIP: 'fastship', QUICKEXPRESS: 'quickexpress', RELIABLECOURIER: 'reliable' }

const TONES: Record<string, string> = {
  SHIPMENT_CREATED: 'bg-slate-100 text-slate-700', PICKED_UP: 'bg-sky-100 text-sky-700',
  IN_TRANSIT: 'bg-blue-100 text-blue-700', OUT_FOR_DELIVERY: 'bg-indigo-100 text-indigo-700',
  DELIVERED: 'bg-emerald-100 text-emerald-700', NDR: 'bg-red-100 text-red-700',
  OPEN: 'bg-amber-100 text-amber-800', NEEDS_APPROVAL: 'bg-orange-100 text-orange-800',
  ACTION_SUBMITTED: 'bg-blue-100 text-blue-700', CARRIER_ACCEPTED: 'bg-teal-100 text-teal-700',
  RESOLVED: 'bg-emerald-100 text-emerald-700', ACTION_FAILED: 'bg-red-100 text-red-700',
  ALLOWED: 'bg-emerald-100 text-emerald-700', REQUIRES_APPROVAL: 'bg-orange-100 text-orange-800',
  NEEDS_CLARIFICATION: 'bg-amber-100 text-amber-800', NO_ACTION: 'bg-slate-100 text-slate-700',
}
export const Badge = ({ value }: { value: string }) => (
  <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[value] ?? 'bg-slate-100 text-slate-700'}`}>{nice(value)}</span>
)

export const Card = ({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) => (
  <section className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
    {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>}
    {children}
  </section>
)

export const PageTitle = ({ title, sub }: { title: string; sub?: string }) => (
  <div className="mb-6"><h1 className="text-2xl font-semibold">{title}</h1>{sub && <p className="text-sm text-slate-500">{sub}</p>}</div>
)

export const Btn = ({ children, onClick, disabled, kind = 'primary', type = 'button' }:
  { children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: 'primary' | 'ghost' | 'danger'; type?: 'button' | 'submit' }) => (
  <button type={type} onClick={onClick} disabled={disabled}
    className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
      kind === 'primary' ? 'bg-indigo-600 text-white hover:bg-indigo-700'
      : kind === 'danger' ? 'bg-red-600 text-white hover:bg-red-700'
      : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>{children}</button>
)

export const ErrorBox = ({ error }: { error: string | null }) =>
  error ? <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div> : null

export const Th = ({ children }: { children: ReactNode }) => <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-500">{children}</th>
export const Td = ({ children, className = '' }: { children: ReactNode; className?: string }) => <td className={`px-3 py-2.5 text-sm ${className}`}>{children}</td>

export function useFetch<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    if (!path) return
    try { setData(await api<T>(path)); setError(null) } catch (e: any) { setError(e.message) }
  }, [path])
  useEffect(() => {
    load()
    if (!pollMs) return
    const t = setInterval(load, pollMs)
    return () => clearInterval(t)
  }, [load, pollMs])
  return { data, error, reload: load, setData }
}

export const ago = (iso: string) => new Date(iso).toLocaleString()
