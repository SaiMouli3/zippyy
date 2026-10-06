import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button, Card, Empty, ErrorBanner, PageHeader, Spinner, StatusBadge, Table, Td, Th } from '@/components/ui'
import { carrierName, dtShort, money } from '@/lib/format'

export default function Orders() {
  const q = useQuery({ queryKey: ['orders'], queryFn: api.orders, refetchInterval: 5000 })
  const ships = useQuery({ queryKey: ['shipments'], queryFn: api.shipments, refetchInterval: 5000 })
  const track = new Map((ships.data?.shipments ?? []).map(s => [s.zippyOrderId, s]))
  return (
    <>
      <PageHeader title="Orders & shipments" actions={<Link to="/orders/new"><Button variant="primary">Create order</Button></Link>} />
      <ErrorBanner error={q.error} />
      <Card pad={false}>
        {q.isLoading ? <Spinner /> : (q.data?.orders ?? []).length === 0 ? <Empty title="No orders yet" hint="Create your first order to start the flow." /> : (
          <Table>
            <thead><tr><Th>Order</Th><Th>Merchant order</Th><Th>Customer</Th><Th>Route</Th><Th>Carrier</Th><Th>Tracking</Th><Th right>Quoted</Th><Th>Status</Th><Th>Created</Th></tr></thead>
            <tbody>
              {q.data!.orders.map(o => {
                const s = track.get(o.orderId)
                return (
                  <tr key={o.id} className="hover:bg-surface2">
                    <Td><Link className="font-medium text-brand" to={`/orders/${o.orderId}`}>{o.orderId}</Link></Td>
                    <Td mono>{o.merchantOrderId}</Td>
                    <Td>{o.customer.name}</Td>
                    <Td className="tabular text-ink2">{o.pickupAddress.pincode} → {o.deliveryAddress.pincode}</Td>
                    <Td>{o.selectedCarrierCode ? carrierName(o.selectedCarrierCode) : '—'}</Td>
                    <Td mono>{s ? <Link className="text-brand" to={`/orders/${o.orderId}/tracking`}>{s.trackingNumber}</Link> : '—'}</Td>
                    <Td right>{money(o.quotedAmount)}</Td>
                    <Td><StatusBadge status={o.status} /></Td>
                    <Td className="text-ink2">{dtShort(o.createdAt)}</Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
