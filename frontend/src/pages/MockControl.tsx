import { useState } from 'react'
import { api } from '../api'
import { Badge, Btn, Card, CARRIER_NAMES, CARRIER_SLUG, ErrorBox, PageTitle, nice, useFetch } from '../ui'

const ACTIONS: [string, string][] = [['Pickup', 'PICKED_UP'], ['In Transit', 'IN_TRANSIT'], ['Out For Delivery', 'OUT_FOR_DELIVERY'], ['Trigger NDR', 'NDR'], ['Delivered', 'DELIVERED']]
const REASONS = ['CUSTOMER_UNAVAILABLE', 'CUSTOMER_REFUSED', 'ADDRESS_ISSUE', 'PHONE_UNREACHABLE', 'COD_NOT_READY']

export default function MockControl() {
  const { data: shipments, reload } = useFetch<any[]>('/api/shipments', 3000)
  const [sel, setSel] = useState<string>('')
  const [reason, setReason] = useState(REASONS[0])
  const [log, setLog] = useState<{ sent: any; resp: any; carrier: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const s = shipments?.find((x) => x.trackingNumber === sel) ?? shipments?.[0]

  async function fire(status: string, dup = false) {
    if (!s) return
    setError(null)
    try {
      const eventId = dup && log[0] ? log[0].sent.eventId ?? undefined : undefined
      const r = await api(`/api/mock/${CARRIER_SLUG[s.carrier]}/${s.trackingNumber}/event`, 'POST',
        { status, reason: status === 'NDR' ? reason : undefined, eventId })
      setLog([{ sent: r.sent, resp: r.webhookResponse, carrier: s.carrier }, ...log].slice(0, 6)); reload()
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
          <div className="mt-4 text-sm"><label className="text-slate-500">NDR reason </label>
            <select className="ml-2 rounded-lg border border-slate-300 px-2 py-1" value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => <option key={r} value={r}>{nice(r)}</option>)}
            </select></div>
        </Card>
        <Card title="Webhooks sent">
          {log.length === 0 && <p className="text-sm text-slate-400">Nothing sent yet.</p>}
          <ul className="space-y-3">{log.map((l, i) => (
            <li key={i} className="rounded-lg bg-slate-50 p-3 text-xs">
              <div className="mb-1 font-medium">POST /api/webhooks/{CARRIER_SLUG[l.carrier]} → {l.resp.duplicate ? 'duplicate (ignored)' : l.resp.status}{l.resp.ndrCaseId && ` · ${l.resp.ndrCaseId}`}</div>
              <pre className="overflow-x-auto text-slate-600">{JSON.stringify(l.sent)}</pre>
            </li>))}</ul>
        </Card>
      </div>
    </>
  )
}
