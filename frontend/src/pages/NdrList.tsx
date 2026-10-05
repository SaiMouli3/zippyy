import { Link } from 'react-router-dom'
import { Badge, Card, CARRIER_NAMES, ErrorBox, PageTitle, Td, Th, nice, useFetch } from '../ui'

export default function NdrList() {
  const { data, error } = useFetch<any[]>('/api/ndr', 3000)
  return (
    <>
      <PageTitle title="NDR Cases" sub="Non-delivery reports waiting for buyer action" />
      <ErrorBox error={error} />
      <Card>
        <table className="w-full">
          <thead><tr><Th>Case ID</Th><Th>Order</Th><Th>Customer</Th><Th>Carrier</Th><Th>Reason</Th><Th>Attempt</Th><Th>Status</Th></tr></thead>
          <tbody className="divide-y">
            {data?.map((n) => (
              <tr key={n.id} className="hover:bg-slate-50">
                <Td><Link className="font-medium text-indigo-600 hover:underline" to={`/ndr/${n.id}`}>{n.id}</Link></Td>
                <Td>{n.orderId}</Td><Td>{n.customerName}</Td><Td>{CARRIER_NAMES[n.carrier]}</Td>
                <Td>{nice(n.reason)}</Td><Td>Attempt {n.attemptNumber}</Td><Td><Badge value={n.status} /></Td>
              </tr>))}
            {data?.length === 0 && <tr><Td className="text-slate-400">No NDR cases. Trigger one from Mock Carrier Control.</Td></tr>}
          </tbody>
        </table>
      </Card>
    </>
  )
}
