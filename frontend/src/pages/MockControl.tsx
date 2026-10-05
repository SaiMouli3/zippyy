import { useState } from 'react'
import { api } from '../api'
import { Badge, Btn, Card, CARRIER_NAMES, CARRIER_SLUG, ErrorBox, PageTitle, Td, Th, ago, nice, useFetch } from '../ui'

const ACTIONS: [string, string][] = [['Pickup', 'PICKED_UP'], ['In Transit', 'IN_TRANSIT'], ['Out For Delivery', 'OUT_FOR_DELIVERY'], ['Trigger NDR', 'NDR'], ['Delivered', 'DELIVERED']]
const REASONS = ['CUSTOMER_UNAVAILABLE', 'CUSTOMER_REFUSED', 'ADDRESS_ISSUE', 'PHONE_UNREACHABLE', 'COD_NOT_READY']

export default function MockControl() {
  const { data: shipments, reload } = useFetch<any[]>('/api/shipments', 3000)
  const { data: quarantine, reload: reloadQ } = useFetch<any[]>('/api/webhook-quarantine', 4000)
  const [sel, setSel] = useState<string>('')
  const [reason, setReason] = useState(REASONS[0])
  const [log, setLog] = useState<{ sent: any; resp: any; carrier: string; http: number; status: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const s = shipments?.find((x) => x.trackingNumber === sel) ?? shipments?.[0]

  async function fire(status: string, dup = false) {
    if (!s) return
    setError(null)
    try {
      const last = log[0]?.sent
      const eventId = dup && last ? (last.eventId ?? last.id ?? last.seq) : undefined
      const r = await api(`/api/mock/${CARRIER_SLUG[s.carrier]}/${s.trackingNumber}/event`, 'POST',
        { status, reason: status === 'NDR' ? reason : undefined, eventId })
      setLog([{ sent: r.sent, resp: r.webhookResponse, carrier: s.carrier, http: r.webhookStatus, status }, ...log].slice(0, 6)); reload(); reloadQ()
    } catch (e: any) { setError(e.message) }
  }

  return (
    <>
      <PageTitle title="Mock Carrier Control" sub="Each button makes the mock carrier POST a real webhook to Zippy, in that carrier's own payload format" />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Shipment">
          <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={s?.trackingNumber ?? ''} onChange={(e) => setSel(e.target.value)}>
            {shipments?.map((x) => <option key={x.id} value={x.trackingNumber}>{x.orderId} · {CARRIER_NAMES[x.carrier]} · {x.trackingNumber} · {nice(x.status)}</option>)}
          </select>
          {s && <div className="mt-3 flex items-center gap-2 text-sm text-slate-600">Current status: <Badge value={s.status} /></div>}
          <div className="mt-5 flex flex-wrap gap-2">
            {ACTIONS.map(([label, st]) => <Btn key={st} kind={st === 'NDR' ? 'danger' : 'primary'} onClick={() => fire(st)} disabled={!s}>{label}</Btn>)}
          </div>
          <div className="mt-3"><Btn kind="ghost" onClick={() => fire(log[0].status, true)} disabled={!s || log.length === 0}>Resend last webhook (duplicate)</Btn></div>
          <div className="mt-4 text-sm"><label className="text-slate-500">NDR reason </label>
            <select className="ml-2 rounded-lg border border-slate-300 px-2 py-1" value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => <option key={r} value={r}>{nice(r)}</option>)}
            </select></div>
        </Card>
        <Card title="Webhooks sent">
          {log.length === 0 && <p className="text-sm text-slate-400">Nothing sent yet.</p>}
          <ul className="space-y-3">{log.map((l, i) => (
            <li key={i} className="rounded-lg bg-slate-50 p-3 text-xs">
              <div className="mb-1 font-medium">POST /api/webhooks/{CARRIER_SLUG[l.carrier]} → HTTP {l.http} · {l.resp.status}{l.resp.reason && ` (${l.resp.reason})`}{l.resp.ndrCaseId && ` · ${l.resp.ndrCaseId}`}</div>
              {l.resp.message && <div className="mb-1 text-slate-500">{l.resp.message}</div>}
              <pre className="overflow-x-auto text-slate-600">{JSON.stringify(l.sent)}</pre>
            </li>))}</ul>
        </Card>
      </div>
      <Card title="Webhook quarantine (unknown tracking numbers, invalid transitions, bad payloads)" className="mt-6">
        <table className="w-full"><thead><tr><Th>When</Th><Th>Carrier</Th><Th>Tracking</Th><Th>Reason</Th><Th>Detail</Th></tr></thead>
          <tbody data-testid="quarantine" className="divide-y">
            {quarantine?.slice(0, 8).map((q) => (
              <tr key={q.id}><Td>{ago(q.receivedAt)}</Td><Td>{CARRIER_NAMES[q.carrier] ?? q.carrier}</Td><Td>{q.trackingNumber ?? '–'}</Td>
                <Td><Badge value={q.reason} /></Td><Td className="text-xs text-slate-500">{q.detail?.from ? `${q.detail.from} → ${q.detail.to}` : ''}</Td></tr>))}
            {quarantine?.length === 0 && <tr><Td className="text-slate-400">Nothing quarantined.</Td></tr>}
          </tbody></table>
      </Card>
    </>
  )
}
