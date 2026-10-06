import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, PackageCheck, PackageSearch, Truck, Undo2, Warehouse, Zap } from 'lucide-react'
import type { TriggerResponse } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { Badge, Banner, Button, Card, Empty, ErrorBanner, Field, inputCls, JsonDetails, PageHeader, StatusBadge, Table, Td, Th } from '@/components/ui'
import { carrierName, dt, pretty } from '@/lib/format'

const NDR_REASONS = ['CUST_UNAVAILABLE', 'ADDRESS_ISSUE', 'PHONE_UNREACHABLE', 'COD_NOT_READY', 'CUST_REFUSED', 'FUTURE_DELIVERY', 'ACCESS_RESTRICTED', 'OUT_OF_AREA', 'SUSPECT_FALSE_ATTEMPT']
const FAULTS = [['', 'Healthy'], ['http500', 'HTTP 500'], ['timeout', 'Timeout'], ['malformed', 'Malformed response'], ['unavailable', 'No service on lane']]

interface LogEntry { at: string; event: string; reason?: string; res?: TriggerResponse; error?: string }

export default function MockControl() {
  const qc = useQueryClient()
  const ships = useQuery({ queryKey: ['shipments'], queryFn: api.shipments, refetchInterval: 4000 })
  const [sel, setSel] = useState('')
  const [reason, setReason] = useState('CUST_UNAVAILABLE')
  const [remark, setRemark] = useState('')
  const [dups, setDups] = useState(false)
  const [log, setLog] = useState<LogEntry[]>([])
  const list = ships.data?.shipments ?? []
  useEffect(() => { if (!sel && list.length) setSel((list.find(s => s.currentStatus !== 'DELIVERED' && s.currentStatus !== 'RTO') ?? list[0]).id) }, [list, sel])
  const cur = list.find(s => s.id === sel)

  const trig = useMutation({
    mutationFn: (v: { event: string }) => api.trigger(cur!.carrierCode, cur!.id, { event: v.event, ndrReason: v.event === 'NDR' ? reason : undefined, remark: v.event === 'NDR' && remark ? remark : undefined, duplicates: dups ? 4 : 0 }),
    onSuccess: (res, v) => { setLog(l => [{ at: new Date().toISOString(), event: v.event, reason: v.event === 'NDR' ? reason : undefined, res }, ...l]); refresh() },
    onError: (e, v) => { setLog(l => [{ at: new Date().toISOString(), event: v.event, error: (e as Error).message }, ...l]) },
  })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['shipments'] }); qc.invalidateQueries({ queryKey: ['cases'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); qc.invalidateQueries({ queryKey: ['inbox'] }) }
  const cases = useQuery({ queryKey: ['cases', 'for', cur?.zippyOrderId], queryFn: () => api.cases({ open: true }), enabled: !!cur, refetchInterval: 4000 })
  const myCase = (cases.data?.cases ?? []).find(c => c.shipmentId === cur?.id)

  const btn = (event: string, label: string, Icon: typeof Truck, variant: 'primary' | 'secondary' | 'danger' = 'secondary') => (
    <Button key={event} variant={variant} disabled={!cur} loading={trig.isPending && trig.variables?.event === event} onClick={() => trig.mutate({ event })}><Icon className="h-4 w-4" />{label}</Button>
  )

  return (
    <>
      <PageHeader title="Mock carrier control" subtitle="Each button makes the mock carrier send a real signed webhook to Zippy: normalization, idempotency, status rules and NDR handling all run for real." />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="1 · Select shipment">
            {list.length === 0 ? <Empty title="No shipments yet" hint="Create an order, pick a carrier and create a shipment first." action={<Link to="/orders/new"><Button variant="primary">Create order</Button></Link>} /> : (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Shipment">
                  <select className={inputCls} value={sel} onChange={e => setSel(e.target.value)} aria-label="Shipment">
                    {list.map(s => <option key={s.id} value={s.id}>{s.zippyOrderId} · {s.trackingNumber} · {carrierName(s.carrierCode)}</option>)}
                  </select>
                </Field>
                {cur && <div className="flex items-end gap-3"><div><div className="text-xs text-muted">Current status</div><StatusBadge status={cur.currentStatus} /></div>
                  <Link className="pb-1 text-sm text-brand" to={`/orders/${cur.zippyOrderId}/tracking`}>Open tracking →</Link></div>}
              </div>
            )}
          </Card>

          <Card title="2 · Trigger carrier event">
            <div className="flex flex-wrap gap-2">
              {btn('PICKED_UP', 'Trigger pickup', PackageSearch)}
              {btn('IN_TRANSIT', 'Trigger in transit', Warehouse)}
              {btn('OUT_FOR_DELIVERY', 'Trigger OFD', Truck)}
              {btn('DELIVERED', 'Trigger delivered', PackageCheck, 'primary')}
              {btn('RTO', 'Trigger RTO', Undo2)}
            </div>
            <div className="mt-4 rounded-lg border border-line bg-surface2 p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium"><AlertOctagon className="h-4 w-4 text-bad" aria-hidden /> Failed delivery (NDR)</div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="NDR reason"><select className={inputCls} value={reason} onChange={e => setReason(e.target.value)} aria-label="NDR reason">{NDR_REASONS.map(r => <option key={r} value={r}>{pretty(r)}</option>)}</select></Field>
                <Field label="Carrier remark (optional)" className="sm:col-span-2" hint="Free text; unknown reason codes fall back to AI remark interpretation"><input className={inputCls} value={remark} onChange={e => setRemark(e.target.value)} placeholder="e.g. society security did not allow entry" /></Field>
              </div>
              <div className="mt-3">{btn('NDR', 'Trigger NDR', AlertOctagon, 'danger')}</div>
              {myCase && <div className="mt-3"><Banner tone="info" title={`NDR case ${myCase.caseNumber} is open`}><Link className="text-brand underline" to={`/ndr/${myCase.id}`}>Open the case</Link> to contact the buyer and run the agent.</Banner></div>}
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm text-ink2"><input type="checkbox" checked={dups} onChange={e => setDups(e.target.checked)} /> <Zap className="h-3.5 w-3.5" /> Deliver each webhook 5 times (prove idempotency)</label>
            <p className="mt-1 text-xs text-muted">Triggering an earlier status after DELIVERED demonstrates the transition guard (HTTP 409, event quarantined).</p>
          </Card>

          <Card title="Delivery log" pad={false}>
            {log.length === 0 ? <Empty title="Nothing sent yet" /> : (
              <Table>
                <thead><tr><Th>Time</Th><Th>Event</Th><Th>Zippy response</Th><Th>Details</Th></tr></thead>
                <tbody>
                  {log.map((l, i) => (
                    <tr key={i}>
                      <Td>{dt(l.at)}</Td>
                      <Td>{pretty(l.event)}{l.reason && <div className="text-xs text-muted">{pretty(l.reason)}</div>}</Td>
                      <Td>
                        {l.error ? <Badge tone="bad">{l.error}</Badge> : l.res?.deliveries.map((d, j) => {
                          const body = d.body as { status?: string; error?: { code?: string } } | undefined
                          return <div key={j} className="mb-1 flex items-center gap-1.5"><Badge tone={d.status === 200 ? 'ok' : 'bad'}>HTTP {d.status || 'ERR'}</Badge><span className="text-xs text-ink2">{body?.status ?? body?.error?.code ?? d.error}</span></div>
                        })}
                      </Td>
                      <Td>{l.res && <JsonDetails label="Carrier-native payload" data={l.res.payload} />}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <FaultPanel />
          <InboxPanel />
        </div>
      </div>
    </>
  )
}

function FaultPanel() {
  const qc = useQueryClient()
  const stats = useQuery({ queryKey: ['mockStats'], queryFn: () => api.mockStats('FASTSHIP'), refetchInterval: 4000 })
  const set = useMutation({ mutationFn: (v: { carrier: string; fault?: string; rejectActions?: boolean }) => api.setFault(v.carrier, v), onSuccess: () => qc.invalidateQueries({ queryKey: ['mockStats'] }) })
  const faults = stats.data?.faults ?? {}
  return (
    <Card title="Failure injection">
      <ErrorBanner error={set.error ?? stats.error} />
      <p className="mb-3 text-xs text-muted">Make a carrier misbehave, then fetch rates: successful carriers must still be returned.</p>
      {['FASTSHIP', 'QUICKEXPRESS', 'RELIABLE'].map(c => (
        <Field key={c} label={carrierName(c)} className="mb-2">
          <select className={inputCls} value={faults[c] ?? ''} aria-label={`${carrierName(c)} fault`} onChange={e => set.mutate({ carrier: c, fault: e.target.value })}>
            {FAULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
      ))}
      <label className="mt-2 flex items-center gap-2 text-sm text-ink2"><input type="checkbox" checked={!!stats.data?.rejectActions} onChange={e => set.mutate({ carrier: 'FASTSHIP', rejectActions: e.target.checked })} /> Carriers reject NDR actions</label>
      <div className="mt-4 border-t border-line pt-3">
        <div className="mb-1 text-xs font-medium text-muted">Carrier API calls received</div>
        <dl className="space-y-0.5 text-xs">
          {Object.entries(stats.data?.calls ?? {}).sort().map(([k, v]) => <div key={k} className="flex justify-between"><dt className="font-mono text-ink2">{k}</dt><dd className="tabular">{v}</dd></div>)}
        </dl>
      </div>
    </Card>
  )
}

function InboxPanel() {
  const q = useQuery({ queryKey: ['inbox'], queryFn: api.inbox, refetchInterval: 4000 })
  const tone = (o: string) => (o === 'PROCESSED' ? 'ok' : o === 'DUPLICATE' ? 'info' : 'bad') as 'ok' | 'info' | 'bad'
  return (
    <Card title="Webhook inbox (all deliveries)">
      <ul className="space-y-2">
        {(q.data?.entries ?? []).slice(0, 10).map(e => (
          <li key={e.id} className="flex items-center justify-between gap-2 text-xs">
            <span className="text-ink2">{carrierName(e.carrierCode)}</span><Badge tone={tone(e.outcome)}>{pretty(e.outcome)}</Badge><span className="text-muted">{dt(e.receivedAt)}</span>
          </li>
        ))}
        {(q.data?.entries ?? []).length === 0 && <li className="text-xs text-muted">No webhooks received yet.</li>}
      </ul>
    </Card>
  )
}
