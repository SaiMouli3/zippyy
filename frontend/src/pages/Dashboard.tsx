import { Link } from 'react-router-dom'
import { Badge, Card, CARRIER_NAMES, ErrorBox, PageTitle, Td, Th, nice, useFetch } from '../ui'

export default function Dashboard() {
  const { data, error } = useFetch<any>('/api/dashboard', 4000)
  const t = data?.totals
  const cards: [string, number | undefined][] = [
    ['Total Orders', t?.orders], ['Shipments', t?.shipments], ['In Transit', t?.inTransit],
    ['Delivered', t?.delivered], ['NDR Cases', t?.ndrCases],
  ]
  return (
    <>
      <PageTitle title="Dashboard" sub="Orders, shipments and delivery exceptions at a glance" />
      <ErrorBox error={error} />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        {cards.map(([label, n]) => (
          <Card key={label}><div className="text-sm text-slate-500">{label}</div><div className="mt-1 text-3xl font-semibold">{n ?? '–'}</div></Card>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Recent shipments">
          <table className="w-full"><thead><tr><Th>Order</Th><Th>Customer</Th><Th>Carrier</Th><Th>Status</Th></tr></thead>
            <tbody className="divide-y">
              {data?.recentShipments.map((s: any) => (
                <tr key={s.id}>
                  <Td><Link className="text-indigo-600 hover:underline" to={`/orders/${s.orderId}/tracking`}>{s.orderId}</Link></Td>
                  <Td>{s.customerName}</Td><Td>{CARRIER_NAMES[s.carrier]}</Td><Td><Badge value={s.status} /></Td>
                </tr>))}
            </tbody></table>
        </Card>
        <Card title="Recent NDR cases">
          <table className="w-full"><thead><tr><Th>Case</Th><Th>Order</Th><Th>Reason</Th><Th>Status</Th></tr></thead>
            <tbody className="divide-y">
              {data?.recentNdr.map((n: any) => (
                <tr key={n.id}>
                  <Td><Link className="text-indigo-600 hover:underline" to={`/ndr/${n.id}`}>{n.id}</Link></Td>
                  <Td>{n.orderId}</Td><Td>{nice(n.reason)}</Td><Td><Badge value={n.status} /></Td>
                </tr>))}
              {data && data.recentNdr.length === 0 && <tr><Td className="text-slate-400">No NDR cases yet</Td></tr>}
            </tbody></table>
        </Card>
      </div>
    </>
  )
}
