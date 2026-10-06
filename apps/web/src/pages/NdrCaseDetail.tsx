import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Bot, CheckCircle2, ClipboardCheck, FileSearch, Globe2, Languages, MessageSquare, PackageCheck, Send, ShieldCheck, Truck, User, XCircle } from 'lucide-react'
import type { Approval, CaseDetail, NdrEvent, RuleCheck } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { useSession } from '@/lib/session'
import { Badge, Banner, Button, Card, Empty, ErrorBanner, Field, inputCls, JsonDetails, KV, PageHeader, Spinner, StatusBadge, Table, Td, Th, Tabs } from '@/components/ui'
import { carrierName, dt, dtShort, langName, maskPhone, money, pretty } from '@/lib/format'
import AuditTable from '@/components/AuditTable'

type Tab = 'timeline' | 'conversation' | 'rules' | 'actions' | 'audit'

const SAMPLES: Array<{ label: string; text: string }> = [
  { label: 'EN · tomorrow evening', text: 'Tomorrow evening after 6. Please tell security guard.' },
  { label: 'HI (romanized)', text: 'kal subah 10 baje ke baad aana, gate pe guard ko bolna' },
  { label: 'KN (romanized)', text: 'naale sanje 6 nantara barbeku' },
  { label: 'TE (romanized)', text: 'repu sayantram 6 tarvata ravali' },
  { label: 'TA (romanized)', text: 'naalaikku saayangalam 6 venum' },
  { label: 'Address (same pincode)', text: 'Flat 402, near Metro pillar 12, pincode 110001' },
  { label: 'Address (new pincode)', text: 'Please deliver to my new address, flat 9 near City Mall, pincode 110002' },
  { label: 'Cancel order', text: "I don't want it, please cancel the order" },
  { label: 'No cash', text: "I don't have cash right now" },
  { label: 'Nobody came', text: 'Nobody came to my house, I was at home all day' },
  { label: 'Vague (low confidence)', text: 'please come' },
  { label: 'Yes', text: 'yes' },
  { label: 'Paid', text: 'paid' },
]

const evIcon = (t: string) => {
  if (t.startsWith('CARRIER_NDR')) return Truck
  if (t.includes('BUYER_MESSAGE_SENT') || t.includes('CONTACT') || t === 'AGENT_REPLIED') return Send
  if (t.startsWith('BUYER')) return User
  if (t === 'LANGUAGE_SWITCHED') return Languages
  if (t === 'RULES_CHECKED') return ShieldCheck
  if (t.startsWith('APPROVAL') || t === 'AWAITING_APPROVAL') return ClipboardCheck
  if (t.includes('ACCEPTED') || t === 'REATTEMPT_SCHEDULED' || t === 'CASE_RESOLVED' || t === 'CASE_CLOSED') return CheckCircle2
  if (t.includes('REJECTED') || t.includes('FAILED') || t === 'ESCALATED' || t.includes('ALERT')) return AlertTriangle
  if (t.startsWith('ACTION')) return Truck
  return Bot
}
const actorTone = (a: string) => ({ AGENT: 'brand', BUYER: 'violet', CARRIER: 'info', SELLER: 'warn', OPS: 'warn', SYSTEM: 'neutral' }[a] ?? 'neutral') as 'brand' | 'violet' | 'info' | 'warn' | 'neutral'

function Checks({ checks }: { checks: RuleCheck[] }) {
  return (
    <ul className="mt-2 space-y-1">
      {checks.map((c, i) => (
        <li key={i} className="flex items-start gap-2 text-xs">
          {c.passed ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" aria-label="passed" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" aria-label="failed" />}
          <span><span className="font-mono text-ink">{c.rule}</span> <span className="text-muted">— {c.detail}</span></span>
        </li>
      ))}
    </ul>
  )
}

function Timeline({ events }: { events: NdrEvent[] }) {
  if (events.length === 0) return <Empty title="No events yet" />
  return (
    <ol className="relative ml-3 border-l border-line">
      {events.map(e => {
        const Icon = evIcon(e.eventType)
        const checks = e.eventType === 'RULES_CHECKED' ? (e.data?.checks as RuleCheck[] | undefined) : undefined
        return (
          <li key={e.id} className="mb-5 ml-6 last:mb-0">
            <span className="absolute -left-[13px] grid h-6 w-6 place-items-center rounded-full border border-line bg-surface text-ink2"><Icon className="h-3.5 w-3.5" aria-hidden /></span>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-ink">{pretty(e.eventType)}</span><Badge tone={actorTone(e.actorType)}>{e.actorType.toLowerCase()}</Badge>
              <span className="text-xs text-muted">{dt(e.createdAt)}</span>
            </div>
            <div className="text-sm text-ink2">{e.description}</div>
            {checks && <Checks checks={checks} />}
            {!checks && <JsonDetails data={e.data} />}
          </li>
        )
      })}
    </ol>
  )
}

function Conversation({ d }: { d: CaseDetail }) {
  return (
    <div>
      {d.messages.length === 0 ? <Empty title="No messages yet" hint="Use “Contact buyer” in the agent console." /> : (
        <ul className="space-y-3">
          {d.messages.map(m => {
            const buyer = m.direction === 'INBOUND'
            return (
              <li key={m.id} className={`flex ${buyer ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl border px-3.5 py-2.5 ${buyer ? 'border-transparent bg-brandsoft' : 'border-line bg-surface2'}`}>
                  <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                    <span className="font-medium text-ink2">{buyer ? 'Buyer' : 'Agent'}</span>·<span>{m.channel}</span>·<span className="inline-flex items-center gap-0.5"><Globe2 className="h-3 w-3" />{langName(m.language)}</span>·<span>{dtShort(m.createdAt)}</span>
                    {!buyer && <Badge tone={m.deliveryStatus === 'FAILED' ? 'bad' : 'ok'}>{m.deliveryStatus.toLowerCase()}</Badge>}
                  </div>
                  <div lang={m.language} className="whitespace-pre-wrap text-sm text-ink">{m.originalText}</div>
                  {buyer && m.interpretation && (
                    <div className="mt-2 rounded-lg bg-surface/70 p-2 text-xs text-ink2">
                      <div className="mb-0.5 font-medium">Interpreted (internal, original text preserved)</div>
                      <div>{m.internalText}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5"><Badge tone="violet">{pretty(m.interpretation.intent)}</Badge><Badge tone={m.interpretation.confidence >= 0.75 ? 'ok' : 'warn'}>confidence {(m.interpretation.confidence * 100).toFixed(0)}%</Badge></div>
                    </div>
                  )}
                  {!buyer && m.internalText && m.language !== 'en' && <div className="mt-1.5 border-t border-line pt-1.5 text-xs text-muted">English: {m.internalText}</div>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {d.communicationAttempts.length > 0 && (
        <div className="mt-5">
          <div className="mb-1 text-xs font-medium text-muted">Channel attempts</div>
          <ul className="flex flex-wrap gap-2">
            {d.communicationAttempts.map(a => <li key={a.id}><Badge tone={a.status === 'FAILED' ? 'bad' : a.status === 'DEFERRED' ? 'warn' : 'ok'} title={a.error}>{a.channel} · {a.status.toLowerCase()}</Badge></li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function ApprovalRow({ a, onDone }: { a: Approval; onDone: () => void }) {
  const { role } = useSession()
  const [note, setNote] = useState('')
  const m = useMutation({ mutationFn: (approve: boolean) => api.decide(a.id, approve, note), onSuccess: onDone })
  const eligible = a.status === 'PENDING' && role && a.requiredRoles.includes(role) && !a.grantedRoles.includes(role)
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{pretty(a.kind)}</span><StatusBadge status={a.status} />{!a.blocking && <Badge>non-blocking</Badge>}
        <span className="text-xs text-muted">needs {a.requiredRoles.join(' + ')}{a.grantedRoles.length ? ` · granted: ${a.grantedRoles.join(', ')}` : ''}</span></div>
      <p className="mt-1 text-sm text-ink2">{a.reason}</p>
      {a.buyerRequest && <p className="mt-1 text-xs text-muted">Buyer: “{a.buyerRequest}”</p>}
      <JsonDetails label="Proposed action & evidence" data={{ proposedAction: a.proposedAction, evidence: a.evidence }} />
      {a.decidedBy && <p className="mt-1 text-xs text-muted">Decided by {a.decidedBy}{a.decisionNote ? ` — ${a.decisionNote}` : ''}</p>}
      {a.status === 'PENDING' && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input className={inputCls + ' max-w-xs'} placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} aria-label="Decision note" />
          <Button variant="primary" disabled={!eligible} loading={m.isPending && m.variables === true} onClick={() => m.mutate(true)}>Approve</Button>
          <Button variant="danger" disabled={!eligible} loading={m.isPending && m.variables === false} onClick={() => m.mutate(false)}>Reject</Button>
          {!eligible && <span className="text-xs text-muted">{role ? 'Your role cannot decide this approval.' : 'Switch “Acting as” to Seller or Ops.'}</span>}
        </div>
      )}
      <ErrorBanner error={m.error} />
    </div>
  )
}

export default function NdrCaseDetail({ initialTab = 'timeline' }: { initialTab?: Tab }) {
  const { caseId = '' } = useParams()
  const qc = useQueryClient()
  const { role } = useSession()
  const [tab, setTab] = useState<Tab>(initialTab)
  const q = useQuery({ queryKey: ['case', caseId], queryFn: () => api.caseDetail(caseId), refetchInterval: 3000 })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['case', caseId] }); qc.invalidateQueries({ queryKey: ['approvals'] }); qc.invalidateQueries({ queryKey: ['cases'] }) }

  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBanner error={q.error} />
  const d = q.data!
  const c = d.case
  const lastAction = d.carrierActions[d.carrierActions.length - 1]
  const pendingApprovals = d.approvals.filter(a => a.status === 'PENDING')
  const approvalState = pendingApprovals.length ? `${pendingApprovals.length} pending` : d.approvals.length ? pretty(d.approvals[d.approvals.length - 1].status) : 'None'
  const ruleEvents = d.events.filter(e => e.eventType === 'RULES_CHECKED')

  return (
    <>
      <PageHeader
        crumbs={<><Link to="/ndr" className="text-brand">NDR cases</Link> / {c.caseNumber}</>}
        title={<span className="flex flex-wrap items-center gap-3">{c.caseNumber} <StatusBadge status={c.state} />{c.outcome && <Badge tone={c.outcome === 'DELIVERED' ? 'ok' : 'warn'}>Outcome: {pretty(c.outcome)}</Badge>}</span>}
        subtitle={<>Order <Link className="text-brand" to={`/orders/${c.orderId}`}>{c.orderId}</Link> · tracking <span className="font-mono">{c.trackingNumber}</span> · opened {dt(c.openedAt)}</>} />

      <Card className="mb-4">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
          <KV label="NDR reason"><div className="font-medium">{pretty(c.normalizedReason)}</div><div className="text-xs text-muted">carrier: {c.carrierReasonCode || '—'}{c.reasonSource !== 'MAPPING' ? ` · via ${c.reasonSource.toLowerCase().replace(/_/g, ' ')}` : ''}</div></KV>
          <KV label="Carrier remark">{c.carrierRemark || '—'}</KV>
          <KV label="Attempt">#{c.attemptNumber} of {d.carrierRules?.maxAttempts ?? '?'} <span className="text-xs text-muted">(seller max {d.sellerRules?.maxAttempts})</span></KV>
          <KV label="Carrier">{carrierName(c.carrierCode)}</KV>
          <KV label="Buyer">{c.customerName} <span className="text-xs text-muted">{maskPhone(d.order.customer.phone)}</span></KV>
          <KV label="Case language"><span className="inline-flex items-center gap-1.5"><Languages className="h-3.5 w-3.5 text-muted" aria-hidden />{langName(c.language)} <Badge tone={c.languageSource === 'reply' ? 'ok' : 'neutral'}>source: {c.languageSource}</Badge></span></KV>
          <KV label="Recommended action">{pretty(c.recommendedAction)}</KV>
          <KV label="Actual action">{c.actualAction ? pretty(c.actualAction.replace(/\+/g, ' + ')) : '—'}</KV>
          <KV label="Approval state">{approvalState}</KV>
          <KV label="Carrier action">{lastAction ? <span className="inline-flex items-center gap-2">{pretty(lastAction.actionType)} <StatusBadge status={lastAction.status} /></span> : '—'}</KV>
          <KV label="Buyer intent">{c.buyerIntent ? <span>{pretty(c.buyerIntent.intent)} <span className="text-xs text-muted">{(c.buyerIntent.confidence * 100).toFixed(0)}%</span></span> : '—'}</KV>
          <KV label="Order value">{d.order.paymentType === 'COD' ? `COD ${money(d.order.codAmount)}` : 'Prepaid'}</KV>
        </dl>
      </Card>

      {c.state === 'REATTEMPT_SCHEDULED' && <div className="mb-4"><Banner tone="ok" title="Carrier has accepted the reattempt request">Zippy only tells the buyer this after the carrier confirmed. The next carrier event (OFD / Delivered) closes the case.</Banner></div>}
      {c.state === 'ACTION_SUBMITTED' && <div className="mb-4"><Banner tone="warn" title="Waiting for carrier acceptance">The buyer has only been told the request was submitted.</Banner></div>}
      {c.state === 'AWAITING_APPROVAL' && <div className="mb-4"><Banner tone="warn" title="Waiting for approval">Nothing has been sent to the carrier. Decide the approval below{role ? '' : ' (switch “Acting as” to Seller/Ops first)'}.</Banner></div>}
      {c.state === 'ESCALATED' && <div className="mb-4"><Banner tone="bad" title="Escalated">The agent could not proceed on its own. Use a manual action, contact the buyer again, or retry the carrier action.</Banner></div>}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[
            { id: 'timeline', label: <span className="inline-flex items-center gap-1.5">Timeline <Badge>{d.events.length}</Badge></span> },
            { id: 'conversation', label: <span className="inline-flex items-center gap-1.5"><MessageSquare className="h-3.5 w-3.5" />Conversation <Badge>{d.messages.length}</Badge></span> },
            { id: 'rules', label: 'Rules checked' },
            { id: 'actions', label: <span className="inline-flex items-center gap-1.5">Actions &amp; approvals {pendingApprovals.length > 0 && <Badge tone="warn">{pendingApprovals.length}</Badge>}</span> },
            { id: 'audit', label: <span className="inline-flex items-center gap-1.5"><FileSearch className="h-3.5 w-3.5" />Audit</span> },
          ]} />
          <Card>
            {tab === 'timeline' && <Timeline events={d.events} />}
            {tab === 'conversation' && <Conversation d={d} />}
            {tab === 'rules' && (ruleEvents.length === 0 ? <Empty title="No rules evaluated yet" hint="The deterministic rules engine runs after the buyer replies." /> : (
              <div className="space-y-5">
                {[...ruleEvents].reverse().map(e => (
                  <div key={e.id}>
                    <div className="flex flex-wrap items-center gap-2"><Badge tone="brand">{String(e.data?.outcome)}</Badge><span className="text-sm text-ink2">{e.description}</span><span className="text-xs text-muted">{dt(e.createdAt)}</span></div>
                    <Checks checks={(e.data?.checks as RuleCheck[]) ?? []} />
                  </div>
                ))}
                <p className="text-xs text-muted">The LLM never overrides this engine: it only produces the structured intent that these rules consume.</p>
              </div>
            ))}
            {tab === 'actions' && (
              <div className="space-y-5">
                <section>
                  <h3 className="mb-2 text-sm font-semibold">Approvals</h3>
                  {d.approvals.length === 0 ? <p className="text-sm text-muted">No approvals for this case.</p> : <div className="space-y-3">{d.approvals.map(a => <ApprovalRow key={a.id} a={a} onDone={refresh} />)}</div>}
                </section>
                <section>
                  <h3 className="mb-2 text-sm font-semibold">Carrier actions</h3>
                  {d.carrierActions.length === 0 ? <p className="text-sm text-muted">Nothing has been submitted to the carrier.</p> : (
                    <Table>
                      <thead><tr><Th>Action</Th><Th>Status</Th><Th>Reference</Th><Th>Details</Th><Th>Responded</Th></tr></thead>
                      <tbody>{d.carrierActions.map(a => (
                        <tr key={a.id}><Td>{pretty(a.actionType)}</Td><Td><StatusBadge status={a.status} /></Td><Td mono>{a.carrierReference || '—'}</Td>
                          <Td>{a.reason || ''}<JsonDetails data={a.payload} label="Payload sent" /></Td><Td>{dtShort(a.respondedAt)}</Td></tr>
                      ))}</tbody>
                    </Table>
                  )}
                </section>
              </div>
            )}
            {tab === 'audit' && <AuditTable caseId={c.id} />}
          </Card>
        </div>
        <AgentConsole d={d} onDone={refresh} />
      </div>
    </>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <div className="border-t border-line pt-4 first:border-0 first:pt-0"><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>{children}</div>
}

function AgentConsole({ d, onDone }: { d: CaseDetail; onDone: () => void }) {
  const { role } = useSession()
  const c = d.case
  const [fail, setFail] = useState<string[]>([])
  const [text, setText] = useState('')
  const [channel, setChannel] = useState('WHATSAPP')
  const [msg, setMsg] = useState<ReactNode>(null)
  const contact = useMutation({ mutationFn: () => api.contact(c.id, { simulateFailures: fail }), onSuccess: r => { setMsg(r.deferred ? 'Contact deferred (outside communication hours).' : r.delivered ? `Buyer contacted via ${r.channel}.` : 'All channels failed — seller alerted.'); onDone() } })
  const reply = useMutation({ mutationFn: () => api.buyerReply(c.id, { text, channel }), onSuccess: r => { setMsg(`Intent ${pretty(r.intent.intent)} (${Math.round(r.intent.confidence * 100)}%) → ${r.decision ? pretty(r.decision.outcome) : 'stored'}`); setText(''); onDone() } })
  const proc = useMutation({ mutationFn: (t: string) => api.process(c.id, t), onSuccess: r => { setMsg(r.summary); onDone() } })
  const closed = c.state === 'CLOSED'
  const canContact = ['OPENED', 'BUYER_CONTACT_PENDING', 'ESCALATED'].includes(c.state)
  const err = contact.error ?? reply.error ?? proc.error

  return (
    <Card title="Agent console" className="self-start">
      <div className="space-y-4">
        {msg && <Banner tone="info">{msg}</Banner>}
        <ErrorBanner error={err} />
        <Section title="1 · Contact buyer">
          <div className="mb-2 flex flex-wrap gap-3 text-xs text-ink2">
            <span className="text-muted">Simulate channel outage:</span>
            {['WHATSAPP', 'IVR', 'SMS'].map(ch => (
              <label key={ch} className="flex items-center gap-1"><input type="checkbox" checked={fail.includes(ch)} onChange={e => setFail(f => (e.target.checked ? [...f, ch] : f.filter(x => x !== ch)))} />{ch}</label>
            ))}
          </div>
          <Button variant="primary" disabled={!canContact} loading={contact.isPending} onClick={() => contact.mutate()}><Send className="h-4 w-4" />Contact buyer in {langName(c.language)}</Button>
        </Section>
        <Section title="2 · Simulate buyer reply">
          <textarea aria-label="Buyer reply" className={inputCls + ' h-20 py-2'} placeholder="Type what the buyer would reply…" value={text} onChange={e => setText(e.target.value)} />
          <div className="my-2 flex flex-wrap gap-1.5">
            {SAMPLES.map(s => <button key={s.label} type="button" onClick={() => setText(s.text)} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink2 hover:bg-surface2">{s.label}</button>)}
          </div>
          <div className="flex items-center gap-2">
            <select aria-label="Reply channel" className={inputCls + ' w-32'} value={channel} onChange={e => setChannel(e.target.value)}><option>WHATSAPP</option><option>SMS</option><option>IVR</option></select>
            <Button variant="primary" disabled={closed || !text.trim()} loading={reply.isPending} onClick={() => reply.mutate()}>Send as buyer</Button>
          </div>
        </Section>
        <Section title="3 · Time-outs & recovery">
          <div className="flex flex-wrap gap-2">
            <Button disabled={c.state !== 'BUYER_CONTACT_PENDING'} loading={proc.isPending && proc.variables === 'BUYER_TIMEOUT'} onClick={() => proc.mutate('BUYER_TIMEOUT')}>Buyer no response</Button>
            <Button disabled={c.state !== 'AWAITING_APPROVAL'} loading={proc.isPending && proc.variables === 'SELLER_TIMEOUT'} onClick={() => proc.mutate('SELLER_TIMEOUT')}>Seller no response</Button>
            <Button disabled={!['ESCALATED', 'ACTION_PENDING'].includes(c.state)} loading={proc.isPending && proc.variables === 'RETRY_ACTION'} onClick={() => proc.mutate('RETRY_ACTION')}>Retry carrier action</Button>
          </div>
        </Section>
        {d.approvals.some(a => a.status === 'PENDING') && (
          <Section title="Pending approvals">
            <div className="space-y-3">{d.approvals.filter(a => a.status === 'PENDING').map(a => <ApprovalRow key={a.id} a={a} onDone={onDone} />)}</div>
          </Section>
        )}
        {!closed && (role ? <ManualAction d={d} onDone={onDone} /> : <Section title="Seller / ops action"><p className="text-xs text-muted">Switch “Acting as” to Seller or Ops to submit carrier actions (e.g. supply an alternate phone number).</p></Section>)}
        {closed && <p className="flex items-center gap-2 text-sm text-ink2"><PackageCheck className="h-4 w-4" /> This case is closed.</p>}
      </div>
    </Card>
  )
}

function ManualAction({ d, onDone }: { d: CaseDetail; onDone: () => void }) {
  const [type, setType] = useState('UPDATE_PHONE')
  const [date, setDate] = useState('')
  const [phone, setPhone] = useState('')
  const [line, setLine] = useState('')
  const [pin, setPin] = useState('')
  const [landmark, setLandmark] = useState('')
  const m = useMutation({
    mutationFn: () => api.manualAction(d.case.id, {
      type, date: date || undefined, phone: phone || undefined, landmark: landmark || undefined,
      address: type === 'UPDATE_ADDRESS' ? { addressLine1: line || d.order.deliveryAddress.addressLine1, city: d.order.deliveryAddress.city, state: d.order.deliveryAddress.state, pincode: pin || d.order.deliveryAddress.pincode } : undefined,
    }),
    onSuccess: onDone,
  })
  return (
    <Section title="Seller / ops action">
      <p className="mb-2 text-xs text-muted">Goes through the same rules engine as buyer requests; it cannot bypass carrier capabilities.</p>
      <div className="space-y-2">
        <select aria-label="Action type" className={inputCls} value={type} onChange={e => setType(e.target.value)}>
          {['UPDATE_PHONE', 'REQUEST_REATTEMPT', 'UPDATE_ADDRESS', 'CONVERT_TO_PREPAID', 'INITIATE_RTO'].map(t => <option key={t} value={t}>{pretty(t)}</option>)}
        </select>
        {type === 'UPDATE_PHONE' && <Field label="Alternate phone"><input className={inputCls} inputMode="tel" maxLength={10} value={phone} onChange={e => setPhone(e.target.value)} /></Field>}
        {type === 'REQUEST_REATTEMPT' && <Field label="Preferred date (optional)"><input className={inputCls} type="date" value={date} onChange={e => setDate(e.target.value)} /></Field>}
        {type === 'UPDATE_ADDRESS' && <>
          <Field label="Address line 1"><input className={inputCls} value={line} onChange={e => setLine(e.target.value)} placeholder={d.order.deliveryAddress.addressLine1} /></Field>
          <div className="grid grid-cols-2 gap-2"><Field label="Pincode"><input className={inputCls} value={pin} onChange={e => setPin(e.target.value)} placeholder={d.order.deliveryAddress.pincode} /></Field><Field label="Landmark"><input className={inputCls} value={landmark} onChange={e => setLandmark(e.target.value)} /></Field></div>
        </>}
        <Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Submit action</Button>
        <ErrorBanner error={m.error} />
      </div>
    </Section>
  )
}
