"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Eye, Lock, MessageSquareText, PackageSearch, RefreshCw, RotateCcw, UserRound, UserRoundCog, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ReactNode, useState } from "react";

import { ActionView, DecisionView, RunList, ThreadView, Timeline, TIMELINE_CATS } from "@/components/platform/case-parts";
import { usePoll, useSession } from "@/components/platform/providers";
import {
  Badge, Button, ConfirmDialog, cx, Dialog, ErrorBox, Field, Freshness, LangTag, Mono, Notice, Panel, PanelHeader, Select, Skeleton,
  SlaCell, StatusBadge, Tabs, Textarea, Timestamp,
} from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { absolute, dateOnly, money, pct, window_ } from "@/lib/platform/format";
import {
  AGENT_STATUS, CARRIERS, CONTACTABILITY, ESC_PRIORITY, ESC_REASON, LANG, NDR_REASON, NDR_STATUS, RECOVERY, SHIPMENT_STATUS, title,
} from "@/lib/platform/labels";
import type { CaseDetail, Run, Thread, TimelineItem } from "@/lib/platform/types";

type Tab = "timeline" | "conversation" | "agent";

export function CaseView() {
  const { id } = useParams<{ id: string }>();
  const poll = usePoll();
  const { can } = useSession();
  const [tab, setTab] = useState<Tab>("timeline");
  const [cats, setCats] = useState<string[]>([]);
  const detail = useQuery({ queryKey: ["case", id], queryFn: () => api<CaseDetail>(`/ndr/${id}`), refetchInterval: poll });
  const timeline = useQuery({ queryKey: ["case", id, "timeline"], queryFn: () => api<{ items: TimelineItem[]; generatedAt: string }>(`/ndr/${id}/timeline`), refetchInterval: poll });
  const thread = useQuery({ queryKey: ["case", id, "thread"], queryFn: () => api<Thread>(`/ndr/${id}/conversations`), enabled: tab === "conversation" && can("conversations.read"), refetchInterval: poll });
  const runs = useQuery({ queryKey: ["case", id, "runs"], queryFn: () => api<{ items: Run[] }>(`/ndr/${id}/agent-runs`), enabled: tab === "agent" && can("agent_runs.read"), refetchInterval: poll });

  if (detail.isError) {
    const e = detail.error as ApiError;
    return (
      <div className="space-y-3">
        <BackLink />
        <Panel>{e.status === 404 ? <div className="px-6 py-14 text-center"><p className="font-heading text-[15px] font-bold text-fg-strong">Case not found</p><p className="mt-1 text-[13px] text-fg-muted">It may belong to another workspace, or the link is wrong.</p></div> : <ErrorBox error={e} onRetry={() => detail.refetch()} />}</Panel>
      </div>
    );
  }
  if (detail.isLoading || !detail.data) return <CaseSkeleton />;
  const d = detail.data;
  const c = d.case;
  const closed = ["resolved", "closed_no_response"].includes(c.status);
  const items = (timeline.data?.items ?? []).filter((i) => !cats.length || cats.includes(i.category));

  return (
    <div className="space-y-4">
      <BackLink />
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-[20px] font-semibold tracking-tight text-fg-strong">{c.code}</h1>
            <StatusBadge map={NDR_STATUS} value={c.status} />
            {c.priority === "urgent" && <Badge tone="danger">Urgent</Badge>}
            {c.hasOpenEscalation && <Badge tone="danger" dot={false}>Escalated</Badge>}
            {c.recoveryOutcome && <StatusBadge map={RECOVERY} value={c.recoveryOutcome} />}
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-fg-muted">
            <span>{NDR_REASON[c.reason] ?? c.reason}</span><span aria-hidden>·</span>
            <span>Attempt {c.attempts}</span><span aria-hidden>·</span>
            <span>{CARRIERS[c.carrier] ?? c.carrier} <Mono className="text-[12px] text-fg-muted">{c.awb}</Mono></span><span aria-hidden>·</span>
            <span>Opened <Timestamp iso={c.openedAt} /></span><span aria-hidden>·</span>
            <span>SLA <SlaCell iso={c.slaDueAt} closed={closed} /></span>
          </p>
        </div>
        <CaseActions d={d} onChanged={() => { detail.refetch(); timeline.refetch(); }} />
      </header>

      {d.isDemo && <Notice tone="warn">Simulated case in a demo workspace. Messages, calls and carrier responses below were produced by simulators; no real customer or carrier was involved.</Notice>}

      <div className="flex flex-wrap items-center gap-3 rounded-[10px] border border-zy-ink bg-zy-ink px-4 py-3 text-white">
        <Bot className="h-4 w-4 shrink-0 text-zy-brand" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-2xs font-semibold uppercase tracking-[0.08em] text-white/50">Next step</p>
          <p className="text-[13px] font-medium">{nextStepText(d.nextStep)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-2xs text-white/60">
          <span>Agent</span><StatusBadge map={AGENT_STATUS} value={c.agentStatus} />
          {d.agent.nextRunAt && !closed && !["escalated", "completed", "cancelled", "superseded"].includes(c.agentStatus ?? "") && (new Date(d.agent.nextRunAt).getTime() > Date.now()
            ? <span>resumes {absolute(d.agent.nextRunAt)}</span>
            : <span className="text-[#F6B15A]">scheduled step overdue since {absolute(d.agent.nextRunAt)}</span>)}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel className="min-w-0">
          <Tabs className="px-2" value={tab} onChange={setTab} tabs={[
            { id: "timeline", label: "Timeline", count: timeline.data?.items.length ?? null },
            ...(can("conversations.read") ? [{ id: "conversation" as Tab, label: "Conversation" }] : []),
            ...(can("agent_runs.read") ? [{ id: "agent" as Tab, label: "Agent inspector" }] : []),
          ]} />
          {tab === "timeline" && (
            <div>
              <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2.5">
                {TIMELINE_CATS.map((cat) => {
                  const on = cats.includes(cat.id);
                  return (
                    <button key={cat.id} onClick={() => setCats(on ? cats.filter((x) => x !== cat.id) : [...cats, cat.id])} aria-pressed={on}
                      className={cx("rounded-full border px-2.5 py-0.5 text-2xs font-medium transition-colors", on ? "border-zy-ink bg-zy-ink text-white" : "border-line-strong text-fg hover:bg-zy-paper")}>
                      {cat.label}
                    </button>
                  );
                })}
                {cats.length > 0 && <button onClick={() => setCats([])} className="text-2xs font-medium text-zy-brand hover:underline">Show all</button>}
                <span className="ml-auto"><Freshness at={timeline.data?.generatedAt} fetching={timeline.isFetching} /></span>
              </div>
              <div className="px-4 py-4">
                {timeline.isError ? <ErrorBox error={timeline.error} compact onRetry={() => timeline.refetch()} />
                  : timeline.isLoading ? <div className="space-y-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}</div>
                    : items.length ? <Timeline items={items} /> : <p className="py-8 text-center text-[13px] text-fg-muted">No events in the selected categories.</p>}
              </div>
            </div>
          )}
          {tab === "conversation" && (
            <div className="px-4 py-4">
              {thread.data?.customer && (
                <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-line bg-zy-paper px-3 py-2 text-[12.5px]">
                  <UserRound className="h-4 w-4 text-fg-muted" aria-hidden />
                  <span className="font-medium text-fg-strong">{thread.data.customer.name}</span>
                  <Mono className="text-fg-muted">{thread.data.customer.phoneMasked}</Mono>
                  <span className="text-fg-muted">Language</span>
                  <LangTag code={thread.data.customer.preferredLanguage ?? thread.data.customer.predictedLanguage} confirmed={!!thread.data.customer.preferredLanguage} />
                  {thread.data.customer.optedOut && <Badge tone="danger">Opted out</Badge>}
                </div>
              )}
              {thread.isError ? <ErrorBox error={thread.error} compact /> : thread.isLoading ? <Skeleton className="h-40 w-full" /> : thread.data ? <ThreadView thread={thread.data} /> : null}
            </div>
          )}
          {tab === "agent" && (
            <div className="px-4 py-4">
              <p className="mb-3 text-2xs text-fg-muted">Every tool the agent called, what it was allowed to do, and what came back. Inputs and outputs are stored sanitized; private model reasoning is never recorded.</p>
              {runs.isError ? <ErrorBox error={runs.error} compact /> : runs.isLoading ? <Skeleton className="h-40 w-full" /> : runs.data ? <RunList runs={runs.data.items} /> : null}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader title="What we know" subtitle="Kept separate so a guess is never mistaken for a fact" />
            <div className="divide-y divide-line">
              <Source icon={<PackageSearch className="h-3.5 w-3.5" />} label="Reported by the courier">
                <Row k="Reason">{NDR_REASON[d.courierReported.reason] ?? d.courierReported.reason}</Row>
                <Row k="Courier remark">{d.courierReported.carrierReason ? <q className="italic">{d.courierReported.carrierReason}</q> : <span className="text-fg-subtle">None given</span>}</Row>
                <Row k="Attempt">{d.courierReported.attempt}</Row>
              </Source>
              <Source icon={<MessageSquareText className="h-3.5 w-3.5" />} label="Said by the customer">
                {d.customerSupplied.preferredDate || d.customerSupplied.preferenceStatus ? <>
                  <Row k="Preferred slot">{d.customerSupplied.preferredDate ? `${dateOnly(d.customerSupplied.preferredDate)}${d.customerSupplied.preferredWindow ? ` · ${window_(d.customerSupplied.preferredWindow)}` : ""}` : "—"}</Row>
                  <Row k="Preference">{title(d.customerSupplied.preferenceStatus)}</Row>
                  <Row k="Via">{title(d.customerSupplied.channel)}{d.customerSupplied.confirmedAt ? <> · <Timestamp iso={d.customerSupplied.confirmedAt} /></> : null}</Row>
                </> : <p className="text-[12.5px] text-fg-muted">No preference captured yet.</p>}
                <Row k="Language">{d.customerSupplied.languageConfirmed ? <>{LANG[d.customerSupplied.languageConfirmed]} <span className="text-fg-subtle">(confirmed)</span></> : <span className="text-fg-subtle">Not confirmed</span>}</Row>
              </Source>
              <Source icon={<Bot className="h-3.5 w-3.5" />} label="Inferred by Zippyy AI" muted>
                <Row k="Intent">{d.aiInferred.intent ? <>{title(d.aiInferred.intent)} <span className="text-fg-subtle">· {pct(d.aiInferred.confidence, 0)} · {d.aiInferred.validation}</span></> : <span className="text-fg-subtle">No reply analysed</span>}</Row>
                <Row k="Extractor">{d.aiInferred.extractor ? <Mono className="text-2xs">{d.aiInferred.extractor}</Mono> : "—"}</Row>
                <Row k="Predicted language">{d.aiInferred.languagePredicted ? <>{LANG[d.aiInferred.languagePredicted] ?? d.aiInferred.languagePredicted} <span className="text-fg-subtle">· {title(d.aiInferred.languagePredictionSource)} · {pct(d.aiInferred.languagePredictionConfidence, 0)}</span></> : "—"}</Row>
              </Source>
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Policy decision" subtitle="Deterministic rules, not the language model" />
            <div className="px-4 py-3"><DecisionView d={d.decision} /></div>
          </Panel>

          <Panel>
            <PanelHeader title="Carrier request" subtitle="Only the carrier's answer counts as confirmation" />
            <div className="px-4 py-3"><ActionView a={d.carrierAction} extra={d.carrierAction && <Reconcile a={d.carrierAction} onDone={() => detail.refetch()} />} /></div>
          </Panel>

          {d.escalation && (
            <Panel>
              <PanelHeader title="Escalation" actions={<Link href={`/escalations/${d.escalation.id}`} className="text-[12px] font-medium text-zy-brand hover:underline">Open</Link>} />
              <div className="space-y-1.5 px-4 py-3 text-[12.5px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Mono>{d.escalation.code}</Mono><StatusBadge map={ESC_PRIORITY} value={d.escalation.priority} />
                  <Badge tone={d.escalation.status === "resolved" ? "muted" : "warn"}>{title(d.escalation.status)}</Badge>
                </div>
                <p className="font-medium text-fg-strong">{ESC_REASON[d.escalation.reason] ?? title(d.escalation.reason)}</p>
                <p className="text-fg-muted">{d.escalation.summary}</p>
              </div>
            </Panel>
          )}

          <Panel>
            <PanelHeader title="Shipment & customer" actions={<Link href={`/shipments/${d.shipment.id}`} className="text-[12px] font-medium text-zy-brand hover:underline">Shipment</Link>} />
            <div className="space-y-1.5 px-4 py-3">
              <Row k="Order">{d.order.ref}</Row>
              <Row k="Payment">{d.order.paymentMode === "COD" ? `COD · ${money(d.order.codAmountPaise)}` : title(d.order.paymentMode?.toLowerCase())}</Row>
              {d.order.orderValuePaise !== null && <Row k="Order value">{money(d.order.orderValuePaise)}</Row>}
              <Row k="Shipment"><StatusBadge map={SHIPMENT_STATUS} value={d.shipment.status} /></Row>
              <Row k="ETA">{d.shipment.etaEnd ? absolute(d.shipment.etaEnd) : "—"}</Row>
              <Row k="Customer">{d.customer?.name ?? "—"}</Row>
              <Row k="Phone"><Mono className="text-[12px]">{d.customer?.phoneMasked ?? "—"}</Mono></Row>
              <Row k="Address">{d.address ? <>{String(d.address.line1Masked ?? "")}, {d.address.city} {d.address.pincode}</> : "—"}</Row>
              <Row k="Contactability"><StatusBadge map={CONTACTABILITY} value={c.contactability} /></Row>
              {d.customer?.optedOut && <p className="text-2xs text-danger">Customer opted out — automated contact is stopped.</p>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function nextStepText(s: string): string {
  // The API renders ISO timestamps inside the sentence; show them in IST like everywhere else.
  return s.replace(/\d{4}-\d{2}-\d{2}T[\d:.]+(?:\+00:00|Z)/g, (m) => absolute(m));
}

function BackLink() {
  return <Link href="/ndr" className="inline-flex items-center gap-1 text-[12.5px] text-fg-muted hover:text-fg-strong"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> NDR cases</Link>;
}

function Source({ icon, label, children, muted }: { icon: ReactNode; label: string; children: ReactNode; muted?: boolean }) {
  return (
    <section className={cx("px-4 py-3", muted && "bg-zy-paper")}>
      <h3 className="mb-2 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.06em] text-fg-muted">{icon}{label}</h3>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] items-baseline gap-2 text-[12.5px]">
      <span className="text-fg-subtle">{k}</span><span className="min-w-0 break-words text-fg-strong">{children}</span>
    </div>
  );
}

function Reconcile({ a, onDone }: { a: CaseDetail["carrierAction"] & object; onDone: () => void }) {
  const { can } = useSession();
  const m = useMutation({ mutationFn: () => api<{ outcome: string; status: string }>(`/carrier-actions/${a.id}/reconcile`, { method: "POST" }), onSuccess: onDone });
  if (!can("carrier_actions.reconcile") || !["unknown", "requested", "timed_out", "failed"].includes(a.status)) return null;
  return (
    <div className="mt-2 border-t border-line pt-2">
      <Button size="sm" icon={<RefreshCw className="h-3 w-3" />} loading={m.isPending} onClick={() => m.mutate()}>Ask the carrier for its status</Button>
      <p className="mt-1 text-2xs text-fg-muted">Checks the carrier&apos;s record of this request. It never sends a second request.</p>
      {m.data && <p className="mt-1 text-2xs text-fg">Carrier says: <span className="font-medium">{title(m.data.outcome)}</span> · status now {title(m.data.status)}</p>}
      {m.error && <p className="mt-1 text-2xs text-danger">{(m.error as Error).message}</p>}
    </div>
  );
}

function CaseActions({ d, onChanged }: { d: CaseDetail; onChanged: () => void }) {
  const { can } = useSession();
  const qc = useQueryClient();
  const c = d.case;
  const [dlg, setDlg] = useState<null | "retry" | "escalate" | "close" | "unmask">(null);
  const closed = ["resolved", "closed_no_response"].includes(c.status);
  const done = () => { setDlg(null); onChanged(); qc.invalidateQueries({ queryKey: ["ndr"] }); };
  const retry = useMutation({ mutationFn: () => api(`/ndr/${c.id}/retry`, { method: "POST" }), onSuccess: done });
  const close = useMutation({ mutationFn: (reason: string) => api(`/ndr/${c.id}/resolve`, { method: "POST", body: { resolution: "no_response", reason } }), onSuccess: done });
  const unmask = useMutation({ mutationFn: (reason: string) => api<{ phone: string; email: string | null; address?: Record<string, string | null> }>(`/ndr/${c.id}/unmask`, { method: "POST", body: { reason } }) });
  return (
    <div className="flex flex-wrap items-center gap-2">
      {can("ndr.act") && !closed && <Button icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setDlg("retry")}>Retry contact</Button>}
      {can("ndr.act") && !closed && <Button icon={<UserRoundCog className="h-3.5 w-3.5" />} onClick={() => setDlg("escalate")}>Escalate</Button>}
      {can("pii.unmask") && <Button variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => { unmask.reset(); setDlg("unmask"); }}>Reveal contact</Button>}
      {can("ndr.resolve") && !closed && <Button variant="ghost" icon={<XCircle className="h-3.5 w-3.5" />} onClick={() => setDlg("close")}>Close case</Button>}

      <ConfirmDialog open={dlg === "retry"} onClose={() => setDlg(null)} title="Retry customer contact" confirmLabel="Queue retry" requireReason={false}
        busy={retry.isPending} error={retry.error} onConfirm={() => retry.mutate()}
        ackText="I understand contact limits, quiet hours and opt-outs still apply, so the agent may not contact the customer immediately."
        description="The agent restarts its contact step. It will not send a duplicate of a message already delivered for the same step." />
      <ConfirmDialog open={dlg === "close"} onClose={() => setDlg(null)} title="Close as no response" confirmLabel="Close case" tone="danger"
        busy={close.isPending} error={close.error} onConfirm={(r) => close.mutate(r)} ackText="I understand this stops all automated contact for this case."
        description={<>Closes the case and cancels the agent&apos;s remaining steps. <strong>Delivered</strong> and <strong>RTO</strong> outcomes cannot be set by hand: they are only recorded from carrier tracking events.</>} />
      <EscalateDialog open={dlg === "escalate"} onClose={() => setDlg(null)} caseId={c.id} onDone={done} />
      {dlg === "unmask" && (unmask.data ? (
        <Dialog open onClose={() => setDlg(null)} title="Customer contact details" footer={<Button variant="primary" onClick={() => setDlg(null)}>Hide again</Button>}>
          <div className="space-y-2 text-[13px]">
            <Notice>This view was recorded in the audit log with your reason. Details are hidden again when you close this window.</Notice>
            <Row k="Phone"><Mono>{unmask.data.phone}</Mono></Row>
            {unmask.data.email && <Row k="Email">{unmask.data.email}</Row>}
            {unmask.data.address && <Row k="Address">{[unmask.data.address.line1, unmask.data.address.line2, unmask.data.address.landmark, unmask.data.address.city, unmask.data.address.state, unmask.data.address.pincode].filter(Boolean).join(", ")}</Row>}
          </div>
        </Dialog>
      ) : (
        <ConfirmDialog open onClose={() => setDlg(null)} title="Reveal full contact details" confirmLabel="Reveal" busy={unmask.isPending} error={unmask.error}
          onConfirm={(r) => unmask.mutate(r)} ackText="I need these details for this case, and I understand the reveal is audited."
          description={<span className="inline-flex items-start gap-2"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Phone numbers and addresses are masked by default. Say why you need them.</span>} />
      ))}
    </div>
  );
}

const ESC_CHOICES = ["address_change", "phone_change", "approval_required", "carrier_no_show", "suspicious_message", "contact_failed", "low_confidence"];

function EscalateDialog({ open, onClose, caseId, onDone }: { open: boolean; onClose: () => void; caseId: string; onDone: () => void }) {
  const [reason, setReason] = useState("approval_required");
  const [priority, setPriority] = useState("medium");
  const [summary, setSummary] = useState("");
  const m = useMutation({ mutationFn: () => api<{ id: string; code: string }>(`/ndr/${caseId}/escalate`, { method: "POST", body: { reason, priority, summary: summary.trim() } }), onSuccess: onDone });
  return (
    <Dialog open={open} onClose={onClose} title="Escalate to an operator"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={summary.trim().length < 5} onClick={() => m.mutate()}>Escalate</Button></>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reason"><Select value={reason} onChange={(e) => setReason(e.target.value)} options={ESC_CHOICES.map((r) => ({ value: r, label: ESC_REASON[r] ?? title(r) }))} /></Field>
          <Field label="Priority"><Select value={priority} onChange={(e) => setPriority(e.target.value)} options={["urgent", "high", "medium", "low"].map((p) => ({ value: p, label: ESC_PRIORITY[p].label }))} /></Field>
        </div>
        <Field label="What should the operator know?" hint="At least 5 characters. Visible to everyone handling this case.">
          <Textarea rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={1000} />
        </Field>
        {m.error ? <ErrorBox error={m.error} compact /> : null}
      </div>
    </Dialog>
  );
}

function CaseSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading case">
      <Skeleton className="h-4 w-24" /><Skeleton className="h-7 w-72" /><Skeleton className="h-14 w-full" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]"><Skeleton className="h-96 w-full" /><Skeleton className="h-96 w-full" /></div>
    </div>
  );
}

