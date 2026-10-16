"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, CircleSlash, Headphones, MessageCircle, RotateCcw, ShieldAlert, UserCheck, Wrench } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useState } from "react";

import { ActionView, DecisionView } from "@/components/platform/case-parts";
import { usePoll, useSession } from "@/components/platform/providers";
import {
  Badge, Button, ConfirmDialog, cx, Dialog, ErrorBox, Field, Freshness, Input, LangTag, Mono, Notice, Panel, PanelHeader, Select,
  Skeleton, SlaCell, StatusBadge, Textarea, Timestamp,
} from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { CALL_RESULT, CALL_STATUS, CARRIERS, ESC_PRIORITY, ESC_REASON, LANG, MESSAGE_STATUS, NDR_REASON, title } from "@/lib/platform/labels";
import type { EscalationDetail } from "@/lib/platform/types";

const OUTCOMES: Record<string, string> = {
  customer_contacted_manually: "I contacted the customer myself",
  carrier_contacted_manually: "I contacted the carrier myself",
  action_approved: "Approved action is with the carrier",
  rto_confirmed: "Return to origin is confirmed",
  closed_no_response: "Customer could not be reached",
  duplicate: "Duplicate of another escalation",
  no_action_needed: "No action needed",
};

export function EscalationView() {
  const { id } = useParams<{ id: string }>();
  const poll = usePoll();
  const { can, me } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["escalations", id], queryFn: () => api<EscalationDetail>(`/escalations/${id}`), refetchInterval: poll });
  const [dlg, setDlg] = useState<null | "approve" | "reject" | "supervisor" | "correct" | "resolve" | "retry">(null);
  const refresh = () => { setDlg(null); q.refetch(); qc.invalidateQueries({ queryKey: ["escalations"] }); qc.invalidateQueries({ queryKey: ["case"] }); };

  const decide = useMutation({ mutationFn: (v: { approve: boolean; reason: string }) => api<{ carrierActionStatus?: string }>(`/escalations/${id}/decision`, { method: "POST", body: { ...v, confirm: true } }), onSuccess: refresh });
  const assign = useMutation({ mutationFn: (userId: string | null) => api(`/escalations/${id}/assign`, { method: "POST", body: { userId } }), onSuccess: refresh });
  const supervisor = useMutation({ mutationFn: (reason: string) => api(`/escalations/${id}/supervisor`, { method: "POST", body: { reason } }), onSuccess: refresh });
  const retry = useMutation({ mutationFn: () => api(`/escalations/${id}/retry`, { method: "POST" }), onSuccess: refresh });

  if (q.isError) {
    const e = q.error as ApiError;
    return <div className="space-y-3"><Back /><Panel>{e.status === 404 ? <p className="px-6 py-14 text-center text-[13px] text-fg-muted">Escalation not found in this workspace.</p> : <ErrorBox error={e} onRetry={() => q.refetch()} />}</Panel></div>;
  }
  if (q.isLoading || !q.data) return <div className="space-y-4"><Skeleton className="h-4 w-24" /><Skeleton className="h-8 w-80" /><Skeleton className="h-96 w-full" /></div>;
  const e = q.data;
  const open = e.status !== "resolved";
  const pendingApproval = e.pendingDecision && !["approved", "rejected"].includes(e.pendingDecision.approvalStatus ?? "");
  const mine = e.assignedTo === me.user.id;

  return (
    <div className="space-y-4">
      <Back />
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-[20px] font-semibold tracking-tight text-fg-strong">{e.code}</h1>
            <StatusBadge map={ESC_PRIORITY} value={e.priority} />
            <Badge tone={open ? "warn" : "muted"}>{title(e.status)}</Badge>
            {e.supervisorRequested && <Badge tone="info" dot={false}>Supervisor requested</Badge>}
          </div>
          <p className="mt-1 text-[15px] font-medium text-fg-strong">{ESC_REASON[e.reason] ?? title(e.reason)}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12.5px] text-fg-muted">
            <span>Case <Link href={`/ndr/${e.ndrCaseId}`} className="font-mono text-fg-strong hover:underline">{e.ndrCode}</Link></span><span aria-hidden>·</span>
            <span>{e.customerName ?? "—"}</span><span aria-hidden>·</span>
            <span>{e.carrier ? CARRIERS[e.carrier] ?? e.carrier : "—"} <Mono className="text-[12px] text-fg-muted">{e.awb}</Mono></span><span aria-hidden>·</span>
            <span>{e.ndrReason ? NDR_REASON[e.ndrReason] ?? e.ndrReason : ""} · attempt {e.attempts}</span>
          </p>
        </div>
        <div className="text-right text-[12.5px]">
          {open ? <><p className="text-2xs uppercase tracking-wide text-fg-subtle">Respond by</p><SlaCell iso={e.slaDueAt} /></> : <p className="text-fg-muted">Resolved <Timestamp iso={e.resolvedAt} /></p>}
          <p className="mt-1"><Freshness at={q.dataUpdatedAt} fetching={q.isFetching} /></p>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <Panel>
            <PanelHeader title="Why this needs a person" />
            <div className="px-4 py-3 text-[13px] leading-5 text-fg">{e.summary}</div>
            {!open && e.resolution && (
              <div className="border-t border-line bg-zy-paper px-4 py-2.5 text-[12.5px]">
                <span className="font-medium text-fg-strong">{OUTCOMES[e.resolution] ?? title(e.resolution)}</span>
                {e.resolutionReason && <span className="text-fg-muted"> — {e.resolutionReason}</span>}
              </div>
            )}
          </Panel>

          {e.pendingDecision && (
            <Panel className={cx(pendingApproval && "border-[#F6DDB5]")}>
              <PanelHeader title={pendingApproval ? "Action waiting for your approval" : "Decision"} subtitle="Proposed by the deterministic policy engine from what the customer said" />
              <div className="px-4 py-3"><DecisionView d={e.pendingDecision} /></div>
              {pendingApproval && open && (
                <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
                  {can("escalations.approve") ? <>
                    <Button variant="primary" icon={<CheckCircle2 className="h-3.5 w-3.5" />} onClick={() => setDlg("approve")}>Approve and send to carrier</Button>
                    <Button icon={<CircleSlash className="h-3.5 w-3.5" />} onClick={() => setDlg("reject")}>Reject</Button>
                  </> : <p className="text-[12.5px] text-fg-muted">An ops lead or owner must approve this action.</p>}
                </div>
              )}
            </Panel>
          )}

          <Panel>
            <PanelHeader title="Recent customer contact" subtitle="Latest WhatsApp messages and calls on this case" />
            {e.excerpts.length === 0 && e.calls.length === 0 ? <p className="px-4 py-6 text-center text-[12.5px] text-fg-muted">No contact recorded.</p> : (
              <ul className="divide-y divide-line">
                {e.excerpts.map((m, i) => (
                  <li key={i} className="flex gap-3 px-4 py-2.5 text-[12.5px]">
                    <MessageCircle className={cx("mt-0.5 h-3.5 w-3.5 shrink-0", m.direction === "inbound" ? "text-info" : "text-fg-subtle")} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-fg-muted">
                        <span className="font-medium text-fg">{m.direction === "inbound" ? "Customer" : "Zippyy agent"}</span>
                        <LangTag code={m.language} confirmed={m.direction === "inbound"} />
                        {m.direction === "outbound" && <StatusBadge map={MESSAGE_STATUS} value={m.status} />}
                        <span className="ml-auto"><Timestamp iso={m.at} mode="absolute" /></span>
                      </div>
                      <p className="whitespace-pre-wrap break-words text-fg-strong">{m.body}</p>
                    </div>
                  </li>
                ))}
                {e.calls.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-[12.5px]">
                    <Headphones className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden />
                    <Link href={`/calls/${c.id}`} className="font-mono text-[12px] hover:underline">{c.code}</Link>
                    <StatusBadge map={CALL_STATUS} value={c.status} />
                    {c.result && <StatusBadge map={CALL_RESULT} value={c.result} />}
                    <LangTag code={c.language} confirmed />
                    <span className="ml-auto text-2xs text-fg-muted"><Timestamp iso={c.at} mode="absolute" /></span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Notes e={e} onAdded={() => q.refetch()} />
        </div>

        <div className="space-y-4">
          {open && (
            <Panel>
              <PanelHeader title="Actions" />
              <div className="space-y-2 px-4 py-3">
                {can("escalations.act") && (mine
                  ? <Button className="w-full" icon={<UserCheck className="h-3.5 w-3.5" />} loading={assign.isPending} onClick={() => assign.mutate(null)}>Unassign me</Button>
                  : <Button className="w-full" variant="dark" icon={<UserCheck className="h-3.5 w-3.5" />} loading={assign.isPending} onClick={() => assign.mutate(me.user.id)}>{e.assignedTo ? `Take over from ${e.assigneeName ?? "colleague"}` : "Assign to me"}</Button>)}
                {can("preferences.correct") && <Button className="w-full" icon={<Wrench className="h-3.5 w-3.5" />} onClick={() => setDlg("correct")}>Correct delivery preference</Button>}
                {can("escalations.act") && can("agent_runs.retry") && <Button className="w-full" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setDlg("retry")}>Restart automated contact</Button>}
                {can("escalations.act") && !e.supervisorRequested && <Button className="w-full" icon={<ShieldAlert className="h-3.5 w-3.5" />} onClick={() => setDlg("supervisor")}>Send to supervisor</Button>}
                {can("escalations.act") && <Button className="w-full" variant="primary" icon={<CheckCircle2 className="h-3.5 w-3.5" />} onClick={() => setDlg("resolve")}>Resolve escalation</Button>}
                {assign.error && <p className="text-2xs text-danger">{(assign.error as Error).message}</p>}
                <p className="pt-1 text-2xs text-fg-muted">Assigned to: <span className="font-medium text-fg">{e.assigneeName ?? "nobody"}</span></p>
              </div>
            </Panel>
          )}
          <Panel>
            <PanelHeader title="Carrier" subtitle="Latest request and its confirmed status" />
            <div className="px-4 py-3"><ActionView a={e.lastCarrierResponse} /></div>
            {e.carrierActions.length > 1 && <p className="border-t border-line px-4 py-2 text-2xs text-fg-muted">{e.carrierActions.length - 1} earlier request{e.carrierActions.length > 2 ? "s" : ""} on this case — see the case timeline.</p>}
          </Panel>
          <Panel>
            <PanelHeader title="Case" actions={<Link href={`/ndr/${e.ndrCaseId}`} className="text-[12px] font-medium text-zy-brand hover:underline">Open case</Link>} />
            <div className="space-y-1.5 px-4 py-3 text-[12.5px]">
              <p className="flex justify-between"><span className="text-fg-subtle">Case SLA</span><SlaCell iso={e.caseSlaDueAt} /></p>
              <p className="flex justify-between"><span className="text-fg-subtle">Delivery attempts</span><span className="num">{e.attempts}</span></p>
              <p className="flex justify-between"><span className="text-fg-subtle">Opened</span><Timestamp iso={e.createdAt} /></p>
            </div>
          </Panel>
        </div>
      </div>

      <ConfirmDialog open={dlg === "approve"} onClose={() => setDlg(null)} title="Approve and send to carrier" confirmLabel="Approve" busy={decide.isPending} error={decide.error}
        onConfirm={(reason) => decide.mutate({ approve: true, reason })}
        description={<>Zippyy will send <strong>{title(e.pendingDecision?.action)}</strong> to {e.carrier ? CARRIERS[e.carrier] ?? e.carrier : "the carrier"}. The case shows <em>Carrier requested</em> until the carrier confirms; approval is not confirmation.</>} />
      <ConfirmDialog open={dlg === "reject"} onClose={() => setDlg(null)} title="Reject proposed action" confirmLabel="Reject" tone="danger" busy={decide.isPending} error={decide.error}
        onConfirm={(reason) => decide.mutate({ approve: false, reason })} ackText="I understand nothing will be sent to the carrier and the agent will be told the action was rejected."
        description="Nothing is sent to the carrier. The agent continues with its next permitted step." />
      <ConfirmDialog open={dlg === "supervisor"} onClose={() => setDlg(null)} title="Send to supervisor" confirmLabel="Send" busy={supervisor.isPending} error={supervisor.error}
        onConfirm={(reason) => supervisor.mutate(reason)} ackText="I understand the priority is raised to at least High."
        description="Flags this escalation for a supervisor and raises its priority." />
      <ConfirmDialog open={dlg === "retry"} onClose={() => setDlg(null)} title="Restart automated contact" confirmLabel="Restart" busy={retry.isPending} error={retry.error} requireReason={false}
        onConfirm={() => retry.mutate()} ackText="I understand contact limits, quiet hours and opt-outs still apply."
        description="The agent restarts its contact step for this case. A note is added to this escalation." />
      <CorrectDialog open={dlg === "correct"} onClose={() => setDlg(null)} id={id} onDone={refresh} />
      <ResolveDialog open={dlg === "resolve"} onClose={() => setDlg(null)} id={id} onDone={refresh} canClose={can("ndr.resolve")} />
    </div>
  );
}

function Back() {
  return <Link href="/escalations" className="inline-flex items-center gap-1 text-[12.5px] text-fg-muted hover:text-fg-strong"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Escalations</Link>;
}

function Notes({ e, onAdded }: { e: EscalationDetail; onAdded: () => void }) {
  const { can } = useSession();
  const [body, setBody] = useState("");
  const m = useMutation({ mutationFn: () => api(`/escalations/${e.id}/notes`, { method: "POST", body: { body: body.trim() } }), onSuccess: () => { setBody(""); onAdded(); } });
  function submit(ev: FormEvent) { ev.preventDefault(); if (body.trim()) m.mutate(); }
  return (
    <Panel>
      <PanelHeader title="Notes & history" subtitle="Every operator action is recorded here and in the audit log" />
      <ol className="divide-y divide-line">
        {e.notes.map((n, i) => (
          <li key={i} className="px-4 py-2.5 text-[12.5px]">
            <div className="mb-0.5 flex flex-wrap items-center gap-2 text-2xs text-fg-muted">
              <span className="font-medium text-fg">{n.author}</span><Badge tone="neutral" dot={false}>{title(n.kind)}</Badge>
              <span className="ml-auto"><Timestamp iso={n.at} mode="absolute" /></span>
            </div>
            <p className="whitespace-pre-wrap break-words text-fg-strong">{n.body}</p>
          </li>
        ))}
      </ol>
      {can("escalations.act") && e.status !== "resolved" && (
        <form onSubmit={submit} className="border-t border-line px-4 py-3">
          <label className="sr-only" htmlFor="note">Add a note</label>
          <Textarea id="note" rows={2} value={body} onChange={(ev) => setBody(ev.target.value)} placeholder="Add a note for whoever picks this up next" maxLength={2000} />
          <div className="mt-2 flex items-center justify-between">
            {m.error ? <span className="text-2xs text-danger">{(m.error as Error).message}</span> : <span />}
            <Button type="submit" size="sm" variant="dark" loading={m.isPending} disabled={!body.trim()}>Add note</Button>
          </div>
        </form>
      )}
    </Panel>
  );
}

function CorrectDialog({ open, onClose, id, onDone }: { open: boolean; onClose: () => void; id: string; onDone: () => void }) {
  const [date, setDate] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [language, setLanguage] = useState("");
  const [reason, setReason] = useState("");
  const windowOk = (!from && !to) || (from && to && from < to);
  const m = useMutation({
    mutationFn: () => api(`/escalations/${id}/correct-preference`, { method: "POST", body: {
      requestedDate: date || null, requestedWindow: from && to ? `${from}-${to}` : null, language: language || null, reason: reason.trim(),
    } }), onSuccess: onDone,
  });
  const ok = reason.trim().length >= 5 && windowOk && (date || language || (from && to));
  return (
    <Dialog open={open} onClose={onClose} title="Correct delivery preference"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={!ok} onClick={() => m.mutate()}>Save correction</Button></>}>
      <div className="space-y-3">
        <Notice>Use this when the customer told you something the agent misunderstood. It records the corrected preference on the case; it does not send anything to the carrier by itself.</Notice>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Delivery date"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Language"><Select value={language} onChange={(e) => setLanguage(e.target.value)} options={[{ value: "", label: "Unchanged" }, ...Object.entries(LANG).map(([v, l]) => ({ value: v, label: l }))]} /></Field>
          <Field label="Window from"><Input type="time" value={from} onChange={(e) => setFrom(e.target.value)} step={1800} /></Field>
          <Field label="Window to" error={windowOk ? undefined : "End must be after start"}><Input type="time" value={to} onChange={(e) => setTo(e.target.value)} step={1800} /></Field>
        </div>
        <Field label="Reason (recorded in the audit log)"><Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field>
        {m.error ? <ErrorBox error={m.error} compact /> : null}
      </div>
    </Dialog>
  );
}

function ResolveDialog({ open, onClose, id, onDone, canClose }: { open: boolean; onClose: () => void; id: string; onDone: () => void; canClose: boolean }) {
  const [outcome, setOutcome] = useState("customer_contacted_manually");
  const [closeCase, setCloseCase] = useState(false);
  const m = useMutation({ mutationFn: (reason: string) => api(`/escalations/${id}/resolve`, { method: "POST", body: { outcome, reason, closeCase: outcome === "closed_no_response" && closeCase } }), onSuccess: onDone });
  return (
    <ConfirmDialog open={open} onClose={onClose} title="Resolve escalation" confirmLabel="Resolve" busy={m.isPending} error={m.error}
      onConfirm={(reason) => m.mutate(reason)} ackText="I understand this is recorded against my name in the audit log."
      description="Pick what actually happened. Delivery and RTO outcomes on the case still come only from carrier tracking.">
      <Field label="Outcome"><Select value={outcome} onChange={(e) => setOutcome(e.target.value)} options={Object.entries(OUTCOMES).map(([value, label]) => ({ value, label }))} /></Field>
      {outcome === "closed_no_response" && canClose && (
        <label className="flex items-center gap-2 text-[12.5px]"><input type="checkbox" checked={closeCase} onChange={(e) => setCloseCase(e.target.checked)} className="accent-[#D54029]" />Also close the NDR case as no response</label>
      )}
    </ConfirmDialog>
  );
}
