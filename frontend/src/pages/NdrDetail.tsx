import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type NdrDetail as Detail } from '../api'
import { Badge, Btn, Card, CARRIER_NAMES, ErrorBox, PageTitle, ago, nice, useFetch } from '../ui'

export default function NdrDetail() {
  const { id } = useParams()
  const { data: c, setData, error: loadErr } = useFetch<Detail>(`/api/ndr/${id}`, 5000)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(path: string, body?: unknown) {
    setBusy(true); setError(null)
    try { setData(await api<Detail>(`/api/ndr/${id}/${path}`, 'POST', body)) }
    catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  async function send() {
    if (!text.trim()) return
    const t = text; setText('')
    await run('message', { message: t })
  }

  if (!c) return <ErrorBox error={loadErr} />
  const contacted = c.messages.length > 0
  const canReattempt = (c.lastDecision?.outcome === 'ALLOWED') && ['OPEN', 'ACTION_FAILED'].includes(c.status)
  const closed = ['ACTION_SUBMITTED', 'CARRIER_ACCEPTED', 'RESOLVED'].includes(c.status)
  const i = c.lastIntent

  return (
    <>
      <PageTitle title={`${c.id} · ${c.orderId}`} sub="NDR case detail" />
      <ErrorBox error={error ?? loadErr} />
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6">
          <Card title="Case">
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-slate-500">Status</dt><dd><Badge value={c.status} /></dd>
              <dt className="text-slate-500">Reason</dt><dd>{nice(c.reason)}</dd>
              <dt className="text-slate-500">Attempt</dt><dd>{c.attemptNumber}</dd>
            </dl>
          </Card>
          <Card title="Customer">
            <div className="text-sm"><div className="font-medium">{c.customerName}</div><div className="text-slate-500">{c.phone}</div>
              <div className="text-slate-500">{c.address}</div><div className="text-slate-500">{c.deliveryPincode}</div>
              <div className="mt-2">{c.paymentMode}{c.paymentMode === 'COD' && ` · ₹${c.codAmount}`}</div></div>
          </Card>
          <Card title="Shipment">
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-slate-500">Carrier</dt><dd>{CARRIER_NAMES[c.carrier]}</dd>
              <dt className="text-slate-500">Tracking</dt><dd>{c.trackingNumber}</dd>
              <dt className="text-slate-500">Status</dt><dd><Badge value={c.shipmentStatus} /></dd>
            </dl>
          </Card>
        </div>

        <Card title="Buyer conversation (simulated WhatsApp)" className="flex flex-col xl:col-span-1">
          <div className="mb-3 flex min-h-64 flex-1 flex-col gap-2 rounded-lg bg-emerald-50/60 p-3">
            {!contacted && <p className="m-auto text-sm text-slate-400">Buyer not contacted yet.</p>}
            {c.messages.map((m) => (
              <div key={m.id} className={`max-w-[85%] rounded-lg px-3 py-2 text-sm shadow-sm ${m.sender === 'AGENT' ? 'self-start bg-white' : 'self-end bg-emerald-200'}`}>
                <div className="mb-0.5 text-[10px] font-semibold uppercase text-slate-500">{m.sender === 'AGENT' ? 'Agent' : 'Buyer'}</div>
                {m.message}
                <div className="mt-1 text-[10px] text-slate-400">{ago(m.timestamp)}</div>
              </div>))}
          </div>
          {!contacted
            ? <Btn onClick={() => run('contact')} disabled={busy}>Contact Buyer</Btn>
            : (
              <div className="flex gap-2">
                <input className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder='Type as buyer, e.g. "Yes tomorrow evening after 6"'
                  value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} disabled={closed || busy} />
                <Btn onClick={send} disabled={closed || busy || !text.trim()}>Send</Btn>
              </div>)}
        </Card>

        <div className="space-y-6">
          <Card title="AI intent → rules → action">
            {!i ? <p className="text-sm text-slate-400">Waiting for the buyer's reply.</p> : (
              <div className="space-y-3 text-sm">
                <div><div className="text-xs uppercase text-slate-500">Extracted intent</div>
                  <div className="font-mono font-medium">{i.intent}</div>
                  <div className="text-slate-600">{i.date && <>Date: {i.date}<br /></>}{(i.timeWindow || i.time) && <>Time: {i.timeWindow ?? i.time}<br /></>}Confidence: {(i.confidence * 100).toFixed(0)}%</div></div>
                <div><div className="text-xs uppercase text-slate-500">Rules engine</div>
                  <Badge value={c.lastDecision!.outcome} />
                  <ul className="mt-1 list-disc pl-5 text-slate-600">{c.lastDecision!.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                  {c.lastDecision!.requestedDate && <div className="text-slate-600">Reattempt on {c.lastDecision!.requestedDate}</div>}</div>
              </div>)}
            <div className="mt-4"><Btn onClick={() => run('reattempt')} disabled={!canReattempt || busy}>Request Reattempt</Btn>
              {i && !canReattempt && !closed && <p className="mt-2 text-xs text-slate-500">Automatic reattempt is not permitted for this request.</p>}</div>
          </Card>
          {c.actions.length > 0 && (
            <Card title="Carrier actions">
              {c.actions.map((a) => (<div key={a.id} className="text-sm"><Badge value={a.status} /> <span className="ml-2 text-slate-600">{a.response?.message ?? 'Submitted…'}</span></div>))}
            </Card>)}
          <Card title="Audit trail">
            <ul className="space-y-1 text-xs">{c.audit.map((a, k) => <li key={k} className="flex justify-between"><span className="font-mono">{a.event}</span><span className="text-slate-400">{new Date(a.createdAt).toLocaleTimeString()}</span></li>)}</ul>
          </Card>
        </div>
      </div>
    </>
  )
}
