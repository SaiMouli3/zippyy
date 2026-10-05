import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Check, Circle } from 'lucide-react'
import { api } from '@/lib/api'
import { Button, Card, ErrorBanner, KV, PageHeader, Spinner, StatusBadge } from '@/components/ui'
import { carrierName, dt, maskPhone, money, langName } from '@/lib/format'
import type { Address } from '@zippy/shared-types'

const STEPS = ['ORDER_CREATED', 'RATES_FETCHED', 'CARRIER_SELECTED', 'SHIPMENT_CREATED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'NDR', 'DELIVERED']

const addr = (a: Address) => (
  <address className="not-italic text-sm text-ink">{a.addressLine1}{a.addressLine2 ? `, ${a.addressLine2}` : ''}<br />{a.city}, {a.state} {a.pincode}</address>
)

export default function OrderDetail() {
  const { orderId = '' } = useParams()
  const q = useQuery({ queryKey: ['tracking', orderId], queryFn: () => api.tracking(orderId), refetchInterval: 4000 })
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBanner error={q.error} />
  const { order: o, shipment, timeline, ndrCases } = q.data!
  const reached = new Set<string>(timeline.map(t => (t.status === 'DELIVERY_FAILED' ? 'NDR' : t.status)))
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-3">{o.orderId} <StatusBadge status={o.status} /></span>} subtitle={`Merchant order ${o.merchantOrderId} · created ${dt(o.createdAt)}`}
        actions={<>
          {!shipment && <Link to={`/orders/${o.orderId}/rates`}><Button variant="primary">{o.selectedCarrierCode ? 'Continue to shipment' : 'Get shipping rates'}</Button></Link>}
          {shipment && <Link to={`/orders/${o.orderId}/tracking`}><Button variant="primary">Tracking</Button></Link>}
          {shipment && <Link to="/mock-carriers"><Button>Mock carrier control</Button></Link>}
        </>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Customer & payment">
            <dl className="grid gap-4 sm:grid-cols-3">
              <KV label="Customer">{o.customer.name}</KV>
              <KV label="Phone">{maskPhone(o.customer.phone)}</KV>
              <KV label="Email">{o.customer.email || '—'}</KV>
              <KV label="Payment">{o.paymentType === 'COD' ? `COD ${money(o.codAmount)}` : 'Prepaid'}</KV>
              <KV label="Order language">{langName(o.language)}</KV>
              <KV label="Merchant">{o.merchantId}</KV>
            </dl>
          </Card>
          <Card title="Addresses & package">
            <dl className="grid gap-4 sm:grid-cols-3">
              <KV label="Pickup">{addr(o.pickupAddress)}</KV>
              <KV label="Delivery">{addr(o.deliveryAddress)}</KV>
              <KV label="Package">{o.package.weightGrams} g · {o.package.lengthCm}×{o.package.widthCm}×{o.package.heightCm} cm</KV>
            </dl>
          </Card>
          <Card title="Carrier & shipment">
            <dl className="grid gap-4 sm:grid-cols-4">
              <KV label="Selected carrier">{carrierName(o.selectedCarrierCode)}</KV>
              <KV label="Service" mono>{o.selectedServiceCode ?? '—'}</KV>
              <KV label="Quoted amount (locked)">{money(o.quotedAmount)}</KV>
              <KV label="Current status"><StatusBadge status={shipment?.currentStatus ?? o.status} /></KV>
              <KV label="Tracking number" mono>{shipment?.trackingNumber ?? '—'}</KV>
              <KV label="Carrier shipment id" mono>{shipment?.carrierShipmentId ?? '—'}</KV>
              <KV label="Selected at">{dt(o.selectedAt)}</KV>
            </dl>
          </Card>
          {ndrCases.length > 0 && (
            <Card title="NDR cases">
              <ul className="space-y-2">
                {ndrCases.map(c => (
                  <li key={c.id} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
                    <Link className="font-medium text-brand" to={`/ndr/${c.id}`}>{c.caseNumber}</Link>
                    <span className="text-sm text-ink2">Attempt {c.attemptNumber} · {c.normalizedReason.replace(/_/g, ' ').toLowerCase()}</span><StatusBadge status={c.state} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <Card title="Lifecycle">
          <ol className="relative space-y-3">
            {STEPS.map(s => {
              const done = reached.has(s)
              return (
                <li key={s} className="flex items-center gap-3 text-sm">
                  {done ? <span className="grid h-5 w-5 place-items-center rounded-full bg-ok text-white"><Check className="h-3 w-3" /></span> : <Circle className="h-5 w-5 text-line" />}
                  <span className={done ? 'text-ink' : 'text-muted'}>{s === 'NDR' ? 'NDR (if delivery fails)' : s.replace(/_/g, ' ')}</span>
                </li>
              )
            })}
          </ol>
        </Card>
      </div>
    </>
  )
}
