export const money = (n: number | undefined | null) =>
  n === undefined || n === null ? '—' : '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const dt = (s?: string | null) =>
  s ? new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'

export const dtShort = (s?: string | null) =>
  s ? new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'

export const pretty = (s?: string | null) => (s ? s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase()) : '—')

export const days = (min: number, max: number) => (min === max ? `${min} day${min === 1 ? '' : 's'}` : `${min}–${max} days`)

export const maskPhone = (p?: string) => (p && p.length > 4 ? 'X'.repeat(p.length - 4) + p.slice(-4) : p ?? '')

export const LANGUAGES: Record<string, string> = { en: 'English', hi: 'Hindi', te: 'Telugu', ta: 'Tamil', kn: 'Kannada' }
export const langName = (c?: string) => (c ? LANGUAGES[c] ?? c : '—')

export const CARRIER_NAMES: Record<string, string> = { FASTSHIP: 'FastShip', QUICKEXPRESS: 'QuickExpress', RELIABLE: 'ReliableCourier' }
export const carrierName = (c?: string) => (c ? CARRIER_NAMES[c] ?? c : '—')

export function bestValue<T extends { totalCharge: number; estimatedMinDays: number; estimatedMaxDays: number }>(opts: T[]): T | undefined {
  if (opts.length === 0) return undefined
  const minP = Math.min(...opts.map(o => o.totalCharge)), maxP = Math.max(...opts.map(o => o.totalCharge))
  const eta = (o: T) => (o.estimatedMinDays + o.estimatedMaxDays) / 2
  const minE = Math.min(...opts.map(eta)), maxE = Math.max(...opts.map(eta))
  const norm = (v: number, lo: number, hi: number) => (hi === lo ? 0 : (v - lo) / (hi - lo))
  return [...opts].sort((a, b) => norm(a.totalCharge, minP, maxP) + norm(eta(a), minE, maxE) - (norm(b.totalCharge, minP, maxP) + norm(eta(b), minE, maxE)))[0]
}
