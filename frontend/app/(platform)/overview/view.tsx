"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { ColumnChart, CHART, Legend, LineChart } from "@/components/platform/charts";
import { useLive, usePoll } from "@/components/platform/providers";
import { RANGES, useRange } from "@/components/platform/shell";
import {
  cx, Empty, ErrorBox, Freshness, PageHeader, Panel, PanelHeader, Skeleton, SlaCell, Timestamp, Tooltip,
} from "@/components/platform/ui";
import { api } from "@/lib/platform/api";
import { money, num, pct } from "@/lib/platform/format";
import { CARRIERS, NDR_REASON } from "@/lib/platform/labels";
import type { Metric, Queues, Summary, Trends } from "@/lib/platform/types";

type KpiDef = { key: string; label: string; good?: "up" | "down" };
const GROUPS: { title: string; items: KpiDef[] }[] = [
  {
    title: "Recovery", items: [
      { key: "openNdr", label: "Open NDR cases" },
      { key: "needsAttention", label: "Needs attention", good: "down" },
      { key: "recovered", label: "Recovered after contact", good: "up" },
      { key: "recoveredOrderValue", label: "Recovered order value", good: "up" },
      { key: "preDeliveryConfirmations", label: "Pre-delivery confirmations", good: "up" },
      { key: "totalShipments", label: "Shipments created" },
    ],
  },
  {
    title: "Customer contact", items: [
      { key: "successfulContacts", label: "Successful contacts", good: "up" },
      { key: "failedWhatsApp", label: "Failed WhatsApp messages", good: "down" },
      { key: "failedCalls", label: "Failed calls", good: "down" },
      { key: "attributableCosts", label: "Reported contact & carrier cost" },
    ],
  },
  {
    title: "Risk", items: [
      { key: "slaAtRisk", label: "SLA due within 4 h", good: "down" },
      { key: "slaBreached", label: "SLA breached", good: "down" },
      { key: "pendingCarrierActions", label: "Carrier requests pending", good: "down" },
      { key: "rtoInitiated", label: "RTO initiated", good: "down" },
      { key: "rtoCompleted", label: "RTO completed", good: "down" },
    ],
  },
];

const QUEUES: { key: string; label: string; hint: string }[] = [
  { key: "urgent", label: "Urgent or past SLA", hint: "Open cases marked urgent, or active cases past their SLA" },
  { key: "escalated", label: "Escalated", hint: "Waiting for an operator decision" },
  { key: "carrier_unknown", label: "Carrier outcome unknown", hint: "The carrier did not answer; reconciliation runs before any retry" },
  { key: "awaiting_carrier", label: "Awaiting carrier", hint: "Request sent, carrier has not confirmed yet" },
  { key: "near_deadline", label: "SLA due within 4 h", hint: "Active cases that breach soon" },
  { key: "callback", label: "Callback requested", hint: "Customer asked to be called back" },
  { key: "call_failures", label: "Call failures", hint: "Last call not answered, busy or failed" },
  { key: "low_confidence", label: "Unclear intent", hint: "Customer reply could not be understood with confidence" },
  { key: "restricted", label: "Contact restricted", hint: "Customer opted out; automated contact stopped" },
];

export function OverviewView() {
  const { range } = useRange();
  const poll = usePoll();
  const summary = useQuery({ queryKey: ["dashboard", "summary", range], queryFn: () => api<Summary>("/dashboard/summary", { query: { range } }), refetchInterval: poll });
  const trendRange = range === "24h" ? "7d" : range;
  const trends = useQuery({ queryKey: ["dashboard", "trends", trendRange], queryFn: () => api<Trends>("/dashboard/trends", { query: { range: trendRange } }), refetchInterval: poll });
  const queues = useQuery({ queryKey: ["queues", "detail"], queryFn: () => api<Queues>("/dashboard/queues"), refetchInterval: poll });
  const rangeLabel = RANGES.find((r) => r.value === range)?.label ?? range;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Delivery recovery across WhatsApp, voice and carriers. Every number links to the cases behind it."
        meta={<>
          <span>{rangeLabel}</span><span aria-hidden>·</span>
          <Freshness at={summary.data?.generatedAt} fetching={summary.isFetching} onRefresh={() => { summary.refetch(); trends.refetch(); queues.refetch(); }} />
          {summary.data && !summary.data.comparisonAvailable && <><span aria-hidden>·</span><span>No earlier period to compare with yet</span></>}
        </>}
      />

      {summary.isError ? <Panel><ErrorBox error={summary.error} onRetry={() => summary.refetch()} /></Panel> : (
        <div className="space-y-4">
          {GROUPS.map((g) => (
            <section key={g.title} aria-labelledby={`kpi-${g.title}`}>
              <h2 id={`kpi-${g.title}`} className="mb-2 text-2xs font-semibold uppercase tracking-[0.08em] text-fg-subtle">{g.title}</h2>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                {g.items.map((k) => <Kpi key={k.key} def={k} metric={summary.data?.metrics[k.key]} loading={summary.isLoading} />)}
              </div>
            </section>
          ))}
        </div>
      )}

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader title="NDR cases opened and resolved" subtitle={`Per day (${trends.data?.dayBasis ?? "UTC"})`}
            actions={<Legend items={[{ label: "Opened", color: CHART.BRAND }, { label: "Resolved", color: CHART.INK }]} />} />
          <div className="px-4 py-3">
            {trends.isError ? <ErrorBox error={trends.error} compact onRetry={() => trends.refetch()} /> : trends.isLoading ? <Skeleton className="h-[180px] w-full" /> : (
              <ColumnChart label="NDR cases opened" data={trends.data!.series.map((p) => ({ x: p.date, y: p.ndrOpened }))}
                secondary={{ label: "Resolved", data: trends.data!.series.map((p) => ({ x: p.date, y: p.ndrResolved })) }} />
            )}
          </div>
        </Panel>
        <Panel>
          <PanelHeader title="Recovery rate" subtitle={trends.data?.definitions.recoveryRate ?? "Recovered after contact ÷ cases resolved"} />
          <div className="px-4 py-3">
            {trends.isError ? <ErrorBox error={trends.error} compact /> : trends.isLoading ? <Skeleton className="h-[160px] w-full" /> : (
              trends.data!.series.every((p) => p.recoveryRate === null)
                ? <Empty title="No closed cases yet">The rate appears once cases are resolved in this period.</Empty>
                : <LineChart label="Recovery rate" data={trends.data!.series.map((p) => ({ x: p.date, y: p.recoveryRate }))} />
            )}
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader title="Queues that need a person" subtitle="Current state, most urgent SLA first"
            actions={<Freshness at={queues.data?.generatedAt} fetching={queues.isFetching} />} />
          {queues.isError ? <ErrorBox error={queues.error} onRetry={() => queues.refetch()} /> : (
            <div className="grid divide-y divide-line md:grid-cols-3 md:divide-x md:divide-y-0">
              {[0, 1, 2].map((col) => (
                <div key={col} className="divide-y divide-line">
                  {QUEUES.filter((_, i) => i % 3 === col).map((q) => <QueueBlock key={q.key} def={q} data={queues.data?.queues[q.key]} loading={queues.isLoading} />)}
                </div>
              ))}
            </div>
          )}
        </Panel>
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Pre-delivery confirmations" subtitle={trends.data?.definitions.preDeliveryRate}
              actions={<Legend items={[{ label: "Started", color: CHART.MUTED }, { label: "Confirmed", color: CHART.OK }]} />} />
            <div className="px-4 py-3">
              {trends.isLoading ? <Skeleton className="h-[140px] w-full" /> : trends.data ? (
                <ColumnChart height={140} label="Pre-delivery started" color={CHART.MUTED} data={trends.data.series.map((p) => ({ x: p.date, y: p.preDeliveryStarted }))}
                  secondary={{ label: "Confirmed", color: CHART.OK, data: trends.data.series.map((p) => ({ x: p.date, y: p.preDeliveryConfirmed })) }} />
              ) : null}
            </div>
          </Panel>
          <LiveFeed />
        </div>
      </div>
    </>
  );
}

function Kpi({ def, metric, loading }: { def: KpiDef; metric?: Metric; loading: boolean }) {
  if (loading || !metric) {
    return <div className="rounded-[10px] border border-line bg-surface p-3.5 shadow-panel"><Skeleton className="w-24" /><Skeleton className="mt-3 h-6 w-16" /></div>;
  }
  const unavailable = metric.basis === "unavailable" || metric.value === null;
  const value = unavailable ? "Not reported" : metric.unit === "paise" ? money(metric.value, { compact: true }) : num(metric.value);
  const prev = metric.previous;
  let delta: { text: string; tone: "ok" | "danger" | "muted"; up: boolean } | null = null;
  if (prev !== undefined && prev !== null && metric.value !== null) {
    const diff = metric.value - prev;
    const up = diff > 0;
    const rel = prev ? Math.abs(diff / prev) : null;
    const tone = diff === 0 || !def.good ? "muted" : (up === (def.good === "up")) ? "ok" : "danger";
    delta = { text: diff === 0 ? "No change" : `${up ? "+" : "−"}${metric.unit === "paise" ? money(Math.abs(diff), { compact: true }) : num(Math.abs(diff))}${rel !== null ? ` (${pct(rel, 0)})` : ""}`, tone, up };
  }
  const body = (
    <>
      <p className="flex items-center justify-between gap-2 text-[12px] font-medium text-fg-muted">
        <span className="truncate">{def.label}</span>
        {metric.href && <ArrowRight className="h-3.5 w-3.5 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />}
      </p>
      <p className={cx("num mt-1.5 font-heading font-bold leading-7 tracking-[-0.01em]", unavailable ? "text-[15px] text-fg-subtle" : "text-[22px] text-fg-strong")}>{value}</p>
      <p className="mt-1 flex min-h-[16px] flex-wrap items-center gap-1 text-2xs">
        {delta ? (
          <span className={cx("inline-flex items-center gap-0.5 font-medium", delta.tone === "ok" ? "text-ok" : delta.tone === "danger" ? "text-danger" : "text-fg-muted")}>
            {delta.text !== "No change" && (delta.up ? <ArrowUpRight className="h-3 w-3" aria-hidden /> : <ArrowDownRight className="h-3 w-3" aria-hidden />)}
            {delta.text}<span className="font-normal text-fg-subtle">&nbsp;vs previous</span>
          </span>
        ) : metric.note === "current" || metric.note?.startsWith("current") ? <span className="text-fg-subtle">Right now</span>
          : <span className="truncate text-fg-subtle">{metric.note ?? ""}</span>}
      </p>
    </>
  );
  const cls = "group block rounded-[10px] border border-line bg-surface p-3.5 shadow-panel transition-colors";
  const tip = metric.note && !metric.note.startsWith("current") ? metric.note : undefined;
  return metric.href
    ? <Link href={metric.href} title={tip} className={cx(cls, "hover:border-line-strong")}>{body}</Link>
    : <div title={tip} className={cls}>{body}</div>;
}

function QueueBlock({ def, data, loading }: { def: { key: string; label: string; hint: string }; data?: Queues["queues"][string]; loading: boolean }) {
  return (
    <div className="px-4 py-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <Tooltip text={def.hint}><Link href={`/ndr?queue=${def.key}`} className="text-[12.5px] font-semibold text-fg-strong hover:underline">{def.label}</Link></Tooltip>
        <span className={cx("num rounded px-1.5 text-[12px] font-semibold", data?.total ? "bg-zy-brand-soft text-zy-brand" : "text-fg-subtle")}>{loading ? "…" : data?.total ?? 0}</span>
      </div>
      {loading ? <Skeleton className="w-full" /> : !data?.items.length ? <p className="text-2xs text-fg-subtle">Nothing waiting</p> : (
        <ul className="space-y-1">
          {data.items.slice(0, 3).map((it) => (
            <li key={it.id}>
              <Link prefetch={false} href={`/ndr/${it.id}`} className="-mx-1.5 flex items-center gap-2 rounded px-1.5 py-1 text-[12px] hover:bg-zy-paper">
                <span className="whitespace-nowrap font-mono text-[11.5px] text-fg-strong">{it.code}</span>
                <span className="min-w-0 flex-1 truncate text-fg-muted">{it.customerName ?? "—"} · {NDR_REASON[it.reason] ?? it.reason} · {CARRIERS[it.carrier] ?? it.carrier}</span>
                <span className="shrink-0"><SlaCell compact iso={it.slaDueAt} closed={["resolved", "closed_no_response"].includes(it.status)} /></span>
              </Link>
            </li>
          ))}
          {data.total > 3 && <li><Link href={`/ndr?queue=${def.key}`} className="text-2xs font-medium text-zy-brand hover:underline">View all {num(data.total)}</Link></li>}
        </ul>
      )}
    </div>
  );
}

const EVENT_LABEL: Record<string, string> = {
  "ndr.opened": "NDR case opened", "ndr.updated": "Another failed attempt", "ndr.resolved": "NDR case closed",
  "ndr.sla_warning": "SLA deadline approaching", "escalation.opened": "Escalation opened", "escalation.assigned": "Escalation assigned",
  "escalation.decision": "Operator decision recorded", "escalation.supervisor": "Sent to supervisor", "escalation.resolved": "Escalation resolved",
  "escalation.updated": "Escalation updated", "message.queued": "WhatsApp message queued", "message.submitted": "WhatsApp accepted the message",
  "message.sent": "WhatsApp: sent", "message.delivered": "WhatsApp: delivered", "message.read": "WhatsApp: read",
  "message.failed": "WhatsApp message failed", "message.received": "Customer replied on WhatsApp", "call.scheduled": "Voice call scheduled",
  "call.initiated": "Voice call dialling", "call.ringing": "Voice call ringing", "call.answered": "Call answered", "call.completed": "Call finished",
  "call.no_answer": "Call not answered", "call.busy": "Line busy", "call.failed": "Call failed", "call.cancelled": "Call cancelled",
  "carrier_action.requested": "Carrier request sent", "carrier_action.accepted": "Carrier accepted request",
  "carrier_action.rejected": "Carrier rejected request", "carrier_action.unknown": "Carrier outcome unknown",
  "carrier_action.completed": "Carrier made the new attempt", "agent_task.started": "Agent workflow started",
  "shipment.out_for_delivery": "Out for delivery", "shipment.delivered": "Delivered", "shipment.rto_initiated": "RTO initiated",
  "shipment.rto_delivered": "Returned to origin",
};

function LiveFeed() {
  const { events, state } = useLive();
  return (
    <Panel>
      <PanelHeader title="Live activity" subtitle={state === "live" ? "Streaming from the event log" : "Stream interrupted — showing what arrived before"} />
      {events.length === 0 ? <p className="px-4 py-6 text-center text-[12.5px] text-fg-muted">No events since you opened this page.</p> : (
        <ul className="max-h-[260px] divide-y divide-line overflow-y-auto scrollbar-thin">
          {events.slice(0, 25).map((e) => {
            const caseId = e.aggregate === "ndr_case" ? e.entityId : (e.payload.ndrCaseId as string | undefined);
            const href = e.aggregate === "escalation" ? `/escalations/${e.entityId}` : caseId ? `/ndr/${caseId}`
              : e.aggregate === "shipment" ? `/shipments/${e.entityId}` : null;
            const code = e.payload.code as string | undefined;
            const content = (
              <div className="flex items-center gap-2 px-4 py-2 text-[12px]">
                <span className="min-w-0 flex-1 truncate text-fg">{EVENT_LABEL[e.type] ?? e.type.replace(/[._]/g, " ")}</span>
                {code ? <span className="font-mono text-[11px] text-fg-muted">{code}</span> : null}
                <span className="shrink-0 text-2xs text-fg-subtle"><Timestamp iso={e.at} /></span>
              </div>
            );
            return <li key={e.id}>{href ? <Link href={href} className="block hover:bg-zy-paper">{content}</Link> : content}</li>;
          })}
        </ul>
      )}
    </Panel>
  );
}
