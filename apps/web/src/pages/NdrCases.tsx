import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Badge, Card, Empty, ErrorBanner, Field, inputCls, PageHeader, Spinner, StatusBadge, Table, Td, Th } from '@/components/ui'
import { carrierName, dtShort, langName, maskPhone, pretty } from '@/lib/format'

const REASONS = ['CUST_UNAVAILABLE', 'CUST_REFUSED', 'ADDRESS_ISSUE', 'PHONE_UNREACHABLE', 'COD_NOT_READY', 'FUTURE_DELIVERY', 'ACCESS_RESTRICTED', 'OUT_OF_AREA', 'SUSPECT_FALSE_ATTEMPT']
const STATES = ['OPENED', 'BUYER_CONTACT_PENDING', 'AWAITING_APPROVAL', 'ACTION_SUBMITTED', 'REATTEMPT_SCHEDULED', 'ESCALATED', 'RTO_INITIATED', 'CLOSED']

export default function NdrCases() {
  const [reason, setReason] = useState('')
  const [state, setState] = useState('')
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: ['cases', reason, state, open], queryFn: () => api.cases({ reason, state, open }), refetchInterval: 4000 })
  return (
    <>
      <PageHeader title="NDR cases" subtitle="Every failed delivery attempt reported by a carrier becomes a case handled by the NDR agent." />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Reason"><select className={inputCls + ' w-56'} value={reason} onChange={e => setReason(e.target.value)}><option value="">All reasons</option>{REASONS.map(r => <option key={r} value={r}>{pretty(r)}</option>)}</select></Field>
          <Field label="State"><select className={inputCls + ' w-56'} value={state} onChange={e => setState(e.target.value)}><option value="">All states</option>{STATES.map(r => <option key={r} value={r}>{pretty(r)}</option>)}</select></Field>
          <label className="flex h-9 items-center gap-2 text-sm text-ink2"><input type="checkbox" checked={open} onChange={e => setOpen(e.target.checked)} /> Open cases only</label>
        </div>
      </Card>
      <ErrorBanner error={q.error} />
      <Card pad={false}>
        {q.isLoading ? <Spinner /> : (q.data?.cases ?? []).length === 0 ? <Empty title="No NDR cases match" hint="Trigger an NDR from Mock carrier control." /> : (
          <Table>
            <thead><tr><Th>Case</Th><Th>Order</Th><Th>Buyer</Th><Th>Carrier</Th><Th>Reason</Th><Th>Attempt</Th><Th>Language</Th><Th>State</Th><Th>Outcome</Th><Th>Opened</Th></tr></thead>
            <tbody>
              {q.data!.cases.map(c => (
                <tr key={c.id} className="hover:bg-surface2">
                  <Td><Link className="font-medium text-brand" to={`/ndr/${c.id}`}>{c.caseNumber}</Link></Td>
                  <Td><Link className="text-ink2 hover:text-brand" to={`/orders/${c.orderId}`}>{c.orderId}</Link></Td>
                  <Td>{c.customerName}<div className="text-xs text-muted">{c.trackingNumber}</div></Td>
                  <Td>{carrierName(c.carrierCode)}</Td>
                  <Td>{pretty(c.normalizedReason)}<div className="text-xs text-muted">{c.carrierReasonCode}</div></Td>
                  <Td right>#{c.attemptNumber}</Td>
                  <Td>{langName(c.language)} <Badge>{c.languageSource}</Badge></Td>
                  <Td><StatusBadge status={c.state} /></Td>
                  <Td>{c.outcome ? <StatusBadge status={c.outcome === 'DELIVERED' ? 'DELIVERED' : c.outcome === 'RTO' ? 'RTO' : 'CLOSED'} /> : '—'}</Td>
                  <Td className="text-ink2">{dtShort(c.openedAt)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p className="mt-2 text-xs text-muted">Buyer phone numbers are masked in lists (e.g. {maskPhone('9876543210')}).</p>
    </>
  )
}
