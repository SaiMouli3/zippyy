import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useSession } from '@/lib/session'
import { Badge, Banner, Button, Card, Empty, ErrorBanner, inputCls, JsonDetails, KV, PageHeader, Spinner, StatusBadge, Tabs } from '@/components/ui'
import { carrierName, dt, pretty } from '@/lib/format'
import type { Approval } from '@zippy/shared-types'

function Row({ a }: { a: Approval }) {
  const { role } = useSession()
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const m = useMutation({ mutationFn: (ok: boolean) => api.decide(a.id, ok, note), onSuccess: () => { qc.invalidateQueries({ queryKey: ['approvals'] }); qc.invalidateQueries({ queryKey: ['case'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) } })
  const eligible = a.status === 'PENDING' && !!role && a.requiredRoles.includes(role) && !a.grantedRoles.includes(role)
  const ev = a.evidence as Record<string, unknown>
  return (
    <Card className="mb-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold">{pretty(a.kind)}</h3><StatusBadge status={a.status} />{!a.blocking && <Badge>non-blocking</Badge>}</div>
          <p className="mt-1 text-sm text-ink2">{a.reason}</p>
        </div>
        <div className="text-xs text-muted">Needs {a.requiredRoles.join(' + ')}{a.grantedRoles.length > 0 && ` · granted by ${a.grantedRoles.join(', ')}`}<br />{dt(a.createdAt)}</div>
      </div>
      <dl className="mt-3 grid gap-4 sm:grid-cols-4">
        <KV label="Order"><Link className="text-brand" to={`/orders/${a.orderId}`}>{a.orderId}</Link></KV>
        <KV label="Shipment" mono>{a.trackingNumber} <span className="font-sans text-xs text-muted">{carrierName(a.carrierCode)}</span></KV>
        <KV label="Case"><Link className="text-brand" to={`/ndr/${a.caseId}`}>{a.caseNumber}</Link></KV>
        <KV label="Buyer request">{a.buyerRequest ? `“${a.buyerRequest}”` : '—'}</KV>
      </dl>
      <div className="mt-3 rounded-lg bg-surface2 p-3 text-sm">
        <div className="mb-1 text-xs font-medium text-muted">Proposed action</div>
        <ul className="space-y-0.5">{(a.proposedAction ?? []).map((p, i) => <li key={i}><b>{pretty(String(p.type))}</b>{p.date ? ` on ${String(p.date)}` : ''}{p.phone ? ` → ${String(p.phone)}` : ''}{p.address ? ` → ${(p.address as { addressLine1: string; addressLine2?: string; pincode: string; city: string }).addressLine1}, ${(p.address as { city: string }).city} ${(p.address as { pincode: string }).pincode}` : ''}</li>)}</ul>
        {typeof ev?.intent === 'object' && <div className="mt-1 text-xs text-muted">Evidence: intent {pretty(String((ev.intent as { intent: string }).intent))}, attempt #{String(ev.attempt)}, carrier remark “{String(ev.carrierRemark ?? '')}”</div>}
      </div>
      <JsonDetails label="Full evidence" data={a.evidence} />
      {a.status === 'PENDING' ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input className={inputCls + ' max-w-xs'} placeholder="Decision note (optional)" value={note} onChange={e => setNote(e.target.value)} aria-label="Decision note" />
          <Button variant="primary" disabled={!eligible} loading={m.isPending && m.variables === true} onClick={() => m.mutate(true)}>Approve</Button>
          <Button variant="danger" disabled={!eligible} loading={m.isPending && m.variables === false} onClick={() => m.mutate(false)}>Reject</Button>
          {!eligible && <span className="text-xs text-muted">{role ? `Role ${role} cannot decide this approval.` : 'Choose Seller or Ops in “Acting as”.'}</span>}
        </div>
      ) : a.decidedBy && <p className="mt-2 text-xs text-muted">Decided by {a.decidedBy} · {dt(a.decidedAt)}{a.decisionNote ? ` — ${a.decisionNote}` : ''}</p>}
      <ErrorBanner error={m.error} />
    </Card>
  )
}

export default function Approvals() {
  const [tab, setTab] = useState<'PENDING' | 'ALL'>('PENDING')
  const { role } = useSession()
  const q = useQuery({ queryKey: ['approvals', tab], queryFn: () => api.approvals(tab === 'PENDING' ? 'PENDING' : undefined), refetchInterval: 4000 })
  return (
    <>
      <PageHeader title="Approvals" subtitle="Actions the agent is not allowed to take on its own. Nothing reaches the carrier until the required roles approve." />
      {!role && <div className="mb-4"><Banner tone="info" title="Read-only">Switch “Acting as” (top right) to Seller or Ops to decide approvals. The backend enforces roles.</Banner></div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'PENDING', label: 'Pending' }, { id: 'ALL', label: 'All' }]} />
      <ErrorBanner error={q.error} />
      {q.isLoading ? <Spinner /> : (q.data?.approvals ?? []).length === 0 ? <Card><Empty title={tab === 'PENDING' ? 'No pending approvals' : 'No approvals yet'} hint="Try buyer messages such as a new pincode or “cancel the order” on an NDR case." /></Card> : q.data!.approvals.map(a => <Row key={a.id} a={a} />)}
    </>
  )
}
