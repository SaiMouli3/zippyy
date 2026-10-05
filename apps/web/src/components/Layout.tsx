import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, Boxes, ClipboardCheck, Gauge, LifeBuoy, Moon, PackagePlus, ScrollText, Settings2, ShieldCheck, Sun, Truck, Wand2 } from 'lucide-react'
import clsx from 'clsx'
import { api } from '@/lib/api'
import { useSession } from '@/lib/session'
import type { Role } from '@zippy/shared-types'

const groups = [
  { title: 'Operate', items: [
    { to: '/', label: 'Dashboard', icon: Gauge, end: true },
    { to: '/orders/new', label: 'Create order', icon: PackagePlus },
    { to: '/orders', label: 'Orders & shipments', icon: Boxes, end: true },
    { to: '/ndr', label: 'NDR cases', icon: LifeBuoy },
    { to: '/approvals', label: 'Approvals', icon: ClipboardCheck, badge: true },
  ] },
  { title: 'Carriers', items: [{ to: '/mock-carriers', label: 'Mock carrier control', icon: Wand2 }] },
  { title: 'Governance', items: [
    { to: '/rules/seller', label: 'Seller rules', icon: ShieldCheck },
    { to: '/rules/carriers', label: 'Carrier rules', icon: Truck },
    { to: '/audit', label: 'Audit logs', icon: ScrollText },
  ] },
]

export default function Layout() {
  const { role, setRole, theme, setTheme } = useSession()
  const approvals = useQuery({ queryKey: ['approvals', 'PENDING'], queryFn: () => api.approvals('PENDING'), refetchInterval: 5000 })
  const pending = (approvals.data?.approvals ?? []).filter(a => a.blocking).length
  const dark = theme === 'dark' || (theme === 'system' && typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches)

  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      <aside className="flex shrink-0 flex-col bg-nav text-[#c9d3e3] lg:sticky lg:top-0 lg:h-screen lg:w-60">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-white" aria-hidden>
            <svg viewBox="0 0 32 32" className="h-5 w-5"><path d="M9 10h14l-9 12h9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <div>
            <div className="text-sm font-semibold text-white">Zippyy Ops</div>
            <div className="text-[11px] text-[#8fa0ba]">Logistics &amp; NDR control</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 lg:flex-1 lg:flex-col lg:overflow-y-auto" aria-label="Main">
          {groups.map(g => (
            <div key={g.title} className="flex gap-1 lg:mb-3 lg:flex-col">
              <div className="hidden px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-[#6f819e] lg:block">{g.title}</div>
              {g.items.map(it => (
                <NavLink key={it.to} to={it.to} end={it.end}
                  className={({ isActive }) => clsx('flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition', isActive ? 'bg-[#1b2d47] text-white' : 'hover:bg-[#15233a] hover:text-white')}>
                  <it.icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="flex-1">{it.label}</span>
                  {'badge' in it && it.badge && pending > 0 && <span className="rounded-full bg-[#eb6834] px-1.5 text-[11px] font-semibold text-white" aria-label={`${pending} pending`}>{pending}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="hidden border-t border-[#1b2d47] p-3 text-xs text-[#8fa0ba] lg:block">
          <a className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:text-white" href="/api/docs" target="_blank" rel="noreferrer"><BookOpen className="h-3.5 w-3.5" /> API documentation</a>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/90 px-5 py-2.5 backdrop-blur">
          <div className="flex items-center gap-2 text-xs text-muted"><Settings2 className="h-3.5 w-3.5" aria-hidden /> Merchant <span className="font-mono text-ink">MRC-100</span></div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-muted">
              Acting as
              <select aria-label="Acting role" value={role} onChange={e => setRole(e.target.value as Role)}
                className="h-8 rounded-lg border border-line bg-surface px-2 text-sm text-ink">
                <option value="">Viewer (read-only)</option>
                <option value="SELLER">Seller</option>
                <option value="OPS">Ops</option>
              </select>
            </label>
            <button aria-label="Toggle theme" onClick={() => setTheme(dark ? 'light' : 'dark')} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-ink2 hover:bg-surface2">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1280px] flex-1 px-5 py-6"><Outlet /></main>
      </div>
    </div>
  )
}
