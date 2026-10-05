import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, CheckCircle2, Circle } from 'lucide-react'
import type { Bucket } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { Card, ErrorBanner, PageHeader, Spinner, StatusBadge, Table, Td, Th, Empty, Button } from '@/components/ui'
import { carrierName, dtShort, langName, pretty } from '@/lib/format'

function Kpi({ label, value, hint, to, tone }: { label: string; value: string | number; hint?: string; to?: string; tone?: string }) {
  const body = (
    <div className="h-full rounded-xl border border-line bg-surface p-4 transition hover:border-brand">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular ${tone ?? 'text-ink'}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
  return to ? <Link to={to} className="block h-full">{body}</Link> : body
}

const axis = { fontSize: 12, fill: 'var(--muted)' }
const tooltipStyle = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12, color: 'var(--ink)' }

function HBar({ data, label, empty }: { data: Bucket[]; label: (k: string) => string; empty: string }) {
  if (data.length === 0) return <Empty title={empty} />
  const rows = data.map(d => ({ name: label(d.key), count: d.count }))
  return (
    <div role="img" aria-label={'Bar chart: ' + rows.map(r => `${r.name} ${r.count}`).join(', ')}>
      <ResponsiveContainer width="100%" height={Math.max(150, rows.length * 38)}>
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }} barCategoryGap={10}>
          <CartesianGrid horizontal={false} stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis type="number" allowDecimals={false} tick={axis} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={150} tick={axis} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} contentStyle={tooltipStyle} />
          <Bar dataKey="count" name="Cases" fill="var(--s1)" radius={[0, 4, 4, 0]} barSize={16} label={{ position: 'right', fontSize: 12, fill: 'var(--ink-2)' }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

const DEMO_STEPS = [
  'Create an order (Create order → submit)',
  'Fetch rates, compare 3 carriers, select one',
  'Create the shipment',
  'Mock carrier control → Pickup → In transit → OFD',
  'Trigger NDR (Customer unavailable)',
  'Open the NDR case → Contact buyer → simulate reply',
  'Watch rules engine → carrier action → acceptance',
  'Trigger Delivered → case closes',
]

export default function Dashboard() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, refetchInterval: 5000 })
  const cases = useQuery({ queryKey: ['cases', 'recent'], queryFn: () => api.cases({}), refetchInterval: 5000 })
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBanner error={q.error} />
  const d = q.data!
  return (
    <>
      <PageHeader title="Operations dashboard" subtitle="Live view of shipments, failed deliveries and agent recovery."
        actions={<Link to="/orders/new"><Button variant="primary">Create order</Button></Link>} />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Orders" value={d.orders} to="/orders" />
        <Kpi label="Shipments" value={d.shipments} to="/orders" />
        <Kpi label="In transit" value={d.inTransit} />
        <Kpi label="Delivered" value={d.delivered} tone="text-ok" />
        <Kpi label="NDR" value={d.ndr} tone={d.ndr ? 'text-bad' : undefined} to="/ndr" hint={`${d.openNdrCases} open case${d.openNdrCases === 1 ? '' : 's'}`} />
        <Kpi label="RTO" value={d.rto} tone={d.rto ? 'text-warn' : undefined} />
        <Kpi label="Recovery rate" value={d.totalNdrCases ? Math.round(d.recoveryRate * 100) + '%' : '—'} hint={`${d.recoveredCases} delivered after NDR`} />
        <Kpi label="Open approvals" value={d.openApprovals} to="/approvals" tone={d.openApprovals ? 'text-warn' : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="NDR by reason"><HBar data={d.ndrByReason} label={pretty} empty="No NDR cases yet" /></Card>
        <Card title="NDR by carrier"><HBar data={d.ndrByCarrier} label={carrierName} empty="No NDR cases yet" /></Card>
        <Card title="NDR outcomes (recovery)"><HBar data={d.ndrRecovery} label={pretty} empty="No NDR cases yet" /></Card>
        <Card title="NDR and RTO events — last 7 days">
          <div role="img" aria-label="Line chart of NDR and RTO events per day">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={d.rtoTrend} margin={{ left: -16, right: 12, top: 8, bottom: 0 }}>
                <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={axis} tickFormatter={(v: string) => v.slice(5)} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={axis} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }} />
                <Line type="monotone" dataKey="ndr" name="NDR" stroke="var(--s1)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
                <Line type="monotone" dataKey="rto" name="RTO" stroke="var(--s2)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Buyer response rate by language" className="lg:col-span-2">
          {d.languageResponse.length === 0 ? <Empty title="No buyer conversations yet" hint="Contact a buyer from an NDR case to see response rates." /> : (
            <Table>
              <thead><tr><Th>Language</Th><Th right>Contacted</Th><Th right>Responded</Th><Th>Response rate</Th></tr></thead>
              <tbody>
                {d.languageResponse.map(l => (
                  <tr key={l.language}>
                    <Td>{langName(l.language)}</Td><Td right>{l.contacted}</Td><Td right>{l.responded}</Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-40 overflow-hidden rounded-full bg-surface2"><div className="h-full rounded-full bg-[var(--s1)]" style={{ width: `${Math.round(l.rate * 100)}%` }} /></div>
                        <span className="tabular text-xs text-ink2">{Math.round(l.rate * 100)}%</span>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Recent NDR cases" className="lg:col-span-2" pad={false}
          actions={<Link to="/ndr" className="inline-flex items-center gap-1 text-xs text-brand">All cases <ArrowRight className="h-3 w-3" /></Link>}>
          {(cases.data?.cases ?? []).length === 0 ? <Empty title="No NDR cases" hint="Trigger an NDR from Mock carrier control to see the agent in action." /> : (
            <Table>
              <thead><tr><Th>Case</Th><Th>Reason</Th><Th>Carrier</Th><Th>State</Th><Th>Opened</Th></tr></thead>
              <tbody>
                {cases.data!.cases.slice(0, 6).map(c => (
                  <tr key={c.id} className="hover:bg-surface2">
                    <Td><Link className="font-medium text-brand" to={`/ndr/${c.id}`}>{c.caseNumber}</Link></Td>
                    <Td>{pretty(c.normalizedReason)}</Td><Td>{carrierName(c.carrierCode)}</Td><Td><StatusBadge status={c.state} /></Td><Td>{dtShort(c.openedAt)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card title="Demo walkthrough">
          <ol className="space-y-2">
            {DEMO_STEPS.map((s, i) => (
              <li key={s} className="flex gap-2 text-sm text-ink2">
                {i < 0 ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-ok" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" />}<span>{s}</span>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  )
}
