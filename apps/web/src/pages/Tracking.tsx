import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { MapPin, PackageCheck, PackageX, Truck, Undo2, Warehouse, Box } from 'lucide-react'
import { api } from '@/lib/api'
import { Button, Card, Empty, ErrorBanner, KV, PageHeader, Spinner, StatusBadge, Table, Td, Th } from '@/components/ui'
import { carrierName, dt, money, pretty } from '@/lib/format'

const icon = (s: string) => ({ DELIVERED: PackageCheck, DELIVERY_FAILED: PackageX, RTO: Undo2, OUT_FOR_DELIVERY: Truck, IN_TRANSIT: Warehouse, PICKED_UP: Box }[s] ?? MapPin)
const color = (s: string) => ({ DELIVERED: 'bg-ok', DELIVERY_FAILED: 'bg-bad', RTO: 'bg-warn' }[s] ?? 'bg-brand')

export default function Tracking() {
  const { orderId = '' } = useParams()
  const q = useQuery({ queryKey: ['tracking', orderId], queryFn: () => api.tracking(orderId), refetchInterval: 3000 })
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBanner error={q.error} />
  const t = q.data!
  const sh = t.shipment
  return (
    <>
      <PageHeader title="Tracking" crumbs={<Link to={`/orders/${orderId}`} className="text-brand">{orderId}</Link>}
        subtitle="Live status and the complete normalized event history (refreshes every 3 seconds)."
        actions={<Link to="/mock-carriers"><Button>Trigger carrier events</Button></Link>} />
      {!sh ? <Card><Empty title="No shipment yet" hint="Select a carrier and create a shipment first." action={<Link to={`/orders/${orderId}/rates`}><Button variant="primary">Go to rates</Button></Link>} /></Card> : (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4">
            <Card title="Shipment">
              <dl className="grid grid-cols-2 gap-4">
                <KV label="Current status"><StatusBadge status={sh.currentStatus} /></KV>
                <KV label="Carrier">{carrierName(sh.carrierCode)}</KV>
                <KV label="Service" mono>{sh.serviceCode}</KV>
                <KV label="Quoted">{money(sh.quotedAmount)}</KV>
                <KV label="Tracking" mono>{sh.trackingNumber}</KV>
                <KV label="Carrier ref" mono>{sh.carrierShipmentId}</KV>
              </dl>
            </Card>
            {t.ndrCases.length > 0 && (
              <Card title="Failed delivery attempts">
                <ul className="space-y-2 text-sm">
                  {t.ndrCases.map(c => (
                    <li key={c.id} className="flex items-center justify-between gap-2">
                      <Link className="font-medium text-brand" to={`/ndr/${c.id}`}>{c.caseNumber}</Link><span className="text-ink2">#{c.attemptNumber} · {pretty(c.normalizedReason)}</span><StatusBadge status={c.state} />
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
          <Card title="Status timeline" className="lg:col-span-2">
            <ol className="relative ml-3 border-l border-line">
              {[...t.timeline].reverse().map((e, i) => {
                const Icon = icon(e.status)
                return (
                  <li key={i} className="mb-5 ml-6 last:mb-0">
                    <span className={`absolute -left-[13px] grid h-6 w-6 place-items-center rounded-full text-white ${color(e.status)}`}><Icon className="h-3.5 w-3.5" aria-hidden /></span>
                    <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{e.label === e.status ? pretty(e.label) : e.label}</span><span className="text-xs text-muted">{dt(e.at)}</span>{e.source === 'ZIPPY' && <span className="rounded bg-surface2 px-1.5 text-[11px] text-muted">Zippy</span>}</div>
                    {(e.description || e.location) && <div className="text-sm text-ink2">{e.description}{e.location ? ` · ${e.location}` : ''}</div>}
                  </li>
                )
              })}
            </ol>
          </Card>
          <Card title="Event history (normalized)" className="lg:col-span-3" pad={false}>
            <Table>
              <thead><tr><Th>Received</Th><Th>Carrier code</Th><Th>Zippy status</Th><Th>Description</Th><Th>Location</Th><Th>Carrier event time</Th></tr></thead>
              <tbody>
                {t.history.map(h => (
                  <tr key={h.id}><Td>{dt(h.receivedAt)}</Td><Td mono>{h.carrierStatus}</Td><Td><StatusBadge status={h.status} /></Td><Td>{h.description}{h.ndrReasonCode ? <span className="ml-1 text-muted">({h.ndrReasonCode})</span> : null}</Td><Td>{h.location || '—'}</Td><Td>{dt(h.eventTime)}</Td></tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      )}
    </>
  )
}
