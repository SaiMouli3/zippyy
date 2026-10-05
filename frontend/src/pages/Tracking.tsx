import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Card, CARRIER_NAMES, ErrorBox, PageTitle, Td, Th, ago, nice, useFetch } from '../ui'

const STEPS = ['SHIPMENT_CREATED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED']

function Picker() {
  const { data } = useFetch<any[]>('/api/shipments', 4000)
  return (
    <Card title="Select a shipment">
      <table className="w-full"><thead><tr><Th>Order</Th><Th>Customer</Th><Th>Carrier</Th><Th>Tracking</Th><Th>Status</Th></tr></thead>
        <tbody className="divide-y">{data?.map((s) => (
          <tr key={s.id}><Td><Link className="text-indigo-600 hover:underline" to={`/orders/${s.orderId}/tracking`}>{s.orderId}</Link></Td>
            <Td>{s.customerName}</Td><Td>{CARRIER_NAMES[s.carrier]}</Td><Td>{s.trackingNumber}</Td><Td><Badge value={s.status} /></Td></tr>))}</tbody></table>
    </Card>
  )
}

export default function Tracking() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data, error } = useFetch<any>(id ? `/api/orders/${id}/tracking?includeRaw=true` : null, 3000)
  if (!id) return (<><PageTitle title="Shipment Tracking" /><Picker /></>)
  const seen = new Set<string>(data?.statusHistory.map((h: any) => h.status))
  return (
    <>
      <PageTitle title={`Tracking · ${id}`} sub={data && `${CARRIER_NAMES[data.carrier]} · ${data.trackingNumber}`} />
      <ErrorBox error={error} />
      {data && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Progress">
            <div className="mb-4"><Badge value={data.currentStatus} /></div>
            <ol className="space-y-3">
              {STEPS.map((s) => (
                <li key={s} className="flex items-center gap-3 text-sm">
                  <span className={`h-3 w-3 rounded-full ${seen.has(s) ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                  <span className={seen.has(s) ? 'font-medium' : 'text-slate-400'}>{nice(s)}</span>
                </li>))}
              {seen.has('NDR') && <li className="flex items-center gap-3 text-sm"><span className="h-3 w-3 rounded-full bg-red-500" /><span className="font-medium text-red-700">Delivery attempt failed (NDR)</span></li>}
            </ol>
          </Card>
          <Card title="Status history">
            <ul className="space-y-2">
              {data.statusHistory.map((h: any, i: number) => (
                <li key={i} className="flex flex-wrap items-center justify-between border-b border-slate-100 pb-2 text-sm">
                  <span><Badge value={h.status} />{h.reason && <span className="ml-2 text-slate-500">{nice(h.reason)}</span>}</span>
                  <span className="text-xs text-slate-400">{ago(h.occurredAt)}</span>
                  {h.raw && h.normalized && h.raw.source !== 'zippy' && (
                    <details className="mt-1 w-full text-xs text-slate-500"><summary className="cursor-pointer">raw / normalized</summary>
                      <pre className="overflow-x-auto">raw: {JSON.stringify(h.raw)}{'\n'}normalized: {JSON.stringify(h.normalized)}</pre></details>)}
                </li>))}
            </ul>
            <div className="mt-4 flex gap-3 text-sm">
              <button className="text-indigo-600 hover:underline" onClick={() => nav('/mock-control')}>Open Mock Carrier Control →</button>
            </div>
          </Card>
        </div>)}
    </>
  )
}
