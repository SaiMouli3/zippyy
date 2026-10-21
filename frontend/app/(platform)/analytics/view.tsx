"use client";

import { useQuery } from "@tanstack/react-query";
import { ReactNode } from "react";

import { HBars } from "@/components/platform/charts";
import { RANGES, useRange } from "@/components/platform/shell";
import { cx, ErrorBox, Freshness, Notice, PageHeader, Panel, PanelHeader, Skeleton, Tabs } from "@/components/platform/ui";
import { api } from "@/lib/platform/api";
import { money, num, pct } from "@/lib/platform/format";
import { useUrlState } from "@/lib/platform/hooks";
import { CALL_RESULT, CALL_STATUS, CARRIERS, LANG, NDR_REASON, title } from "@/lib/platform/labels";

interface Analytics {
  reasons: { reason: string; count: number }[];
  byCarrier: { carrier: string; cases: number; recovered: number; rto: number; open: number; closed: number; recoveryRate: number | null; rtoRate: number | null }[];
  rtoByReason: { reason: string; closed: number; rto: number; rtoRate: number | null }[];
  channels: {
    whatsapp: { sent: number; delivered: number; read: number; deliveryRate: number | null; conversationsContacted: number; conversationsReplied: number; replyRate: number | null };
    voice: { placed: number; answered: number; answerRate: number | null };
  };
  callOutcomes: { outcome: string; count: number }[];
  deliveryAfterContact: { closedWithContact: number; delivered: number; rate: number | null };
  resolution: { resolvedCases: number; avgHours: number | null; medianHours: number | null };
  costPerRecovered: { available: boolean; valuePaise: number | null; recovered: number; measuredCostPaise: number; note: string };
  generatedAt: string;
}
interface Languages {
  inferred: { language: string; count: number }[]; confirmed: { language: string; count: number }[];
  predictionSources: { source: string; count: number }[];
  detectedPerTurn: { language: string; voiceTurns?: number; avgConfidence?: number | null; messages?: number; messageAvgConfidence?: number | null }[];
  calls: { completed: number; withSwitch: number; switchRate: number | null; completedInStartLanguage: number; codeMixedTurns: number; unsupportedLanguage: number; unrecognised: number };
  byLanguageCalls: { language: string | null; calls: number; avgDurationSeconds: number | null; costPaise: number | null }[];
  clarificationByLanguage: { language: string | null; extractions: number; clarificationRate: number | null }[];
  recoveryByLanguage: { language: string | null; closed: number; recovered: number; recoveryRate: number | null }[];
  intentAccuracy: { available: boolean; note: string };
  generatedAt: string;
}
interface Health {
  runs: number; failedRuns: number; runsWithFailedSteps: number; structuredOutputFallbacks: number; extractions: number; deadJobs: number; retriedJobs: number;
  tools: { tool: string; calls: number; failed: number; failureRate: number | null; avgMs: number | null }[]; generatedAt: string;
}

const lang = (c: string | null | undefined) => (c ? LANG[c] ?? (c === "unknown" ? "Not detected" : c) : "Not detected");

export function AnalyticsView() {
  const { range } = useRange();
  const { state: f, set } = useUrlState({ tab: "recovery" });
  const label = RANGES.find((r) => r.value === range)?.label ?? range;
  return (
    <>
      <PageHeader title="Analytics" description="Recovery, channels, languages and agent health. Rates show their numerator and denominator; anything that cannot be measured says so."
        meta={<span>{label} · change the period in the top bar</span>} />
      <Tabs className="mb-4" value={f.tab} onChange={(tab) => set({ tab })}
        tabs={[{ id: "recovery", label: "Recovery" }, { id: "channels", label: "Channels" }, { id: "languages", label: "Languages" }, { id: "agents", label: "Agent health" }]} />
      {f.tab === "languages" ? <LanguagesTab range={range} /> : f.tab === "agents" ? <HealthTab range={range} /> : <MainTabs range={range} tab={f.tab} />}
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-[10px] border border-line bg-surface p-3.5 shadow-panel">
      <p className="text-[12px] font-medium text-fg-muted">{label}</p>
      <p className="num mt-1.5 font-heading text-[22px] font-bold leading-7 text-fg-strong">{value}</p>
      {sub && <p className="mt-1 text-2xs text-fg-subtle">{sub}</p>}
    </div>
  );
}

function Table({ head, rows, empty = "No data in this period" }: { head: string[]; rows: ReactNode[][]; empty?: string }) {
  if (!rows.length) return <p className="px-4 py-6 text-center text-[12.5px] text-fg-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-[12.5px]">
        <thead className="bg-zy-paper"><tr className="border-b border-line">{head.map((h, i) => <th key={i} scope="col" className={cx("whitespace-nowrap px-4 py-2 text-2xs font-semibold uppercase tracking-wide text-fg-muted", i ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={cx("whitespace-nowrap px-4 py-2", j ? "num text-right" : "text-fg-strong")}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

const ratio = (r: number | null, n: number, d: number) => (r === null ? <span className="text-fg-subtle">—</span> : <span title={`${n} of ${d}`}>{pct(r)} <span className="text-2xs text-fg-subtle">({num(n)}/{num(d)})</span></span>);

function MainTabs({ range, tab }: { range: string; tab: string }) {
  const q = useQuery({ queryKey: ["dashboard", "analytics", range], queryFn: () => api<Analytics>("/dashboard/analytics", { query: { range } }) });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!q.data) return <div className="grid gap-3 sm:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}</div>;
  const a = q.data;
  if (tab === "channels") {
    const wa = a.channels.whatsapp, v = a.channels.voice;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="WhatsApp messages sent" value={num(wa.sent)} sub="Accepted by the provider" />
          <Stat label="Delivered to the phone" value={pct(wa.deliveryRate)} sub={`${num(wa.delivered)} of ${num(wa.sent)} · ${num(wa.read)} read`} />
          <Stat label="Customers who replied" value={pct(wa.replyRate)} sub={`${num(wa.conversationsReplied)} of ${num(wa.conversationsContacted)} conversations`} />
          <Stat label="Calls answered" value={pct(v.answerRate)} sub={`${num(v.answered)} of ${num(v.placed)} calls placed`} />
        </div>
        <Panel>
          <PanelHeader title="Call outcomes" subtitle="Result where the call connected, otherwise its final status" actions={<Freshness at={a.generatedAt} />} />
          <div className="px-4 py-3"><HBars items={a.callOutcomes.sort((x, y) => y.count - x.count).map((o) => ({ label: (CALL_RESULT[o.outcome] ?? CALL_STATUS[o.outcome])?.label ?? title(o.outcome), value: o.count, href: `/calls?${CALL_RESULT[o.outcome] ? "result" : "status"}=${o.outcome}` }))} /></div>
        </Panel>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Delivered after contact" value={pct(a.deliveryAfterContact.rate)} sub={`${num(a.deliveryAfterContact.delivered)} of ${num(a.deliveryAfterContact.closedWithContact)} closed cases where the customer was reached`} />
        <Stat label="Median time to resolve" value={a.resolution.medianHours === null ? "—" : `${a.resolution.medianHours} h`} sub={a.resolution.avgHours === null ? "No resolved cases" : `Mean ${a.resolution.avgHours} h over ${num(a.resolution.resolvedCases)} cases`} />
        <Stat label="Cost per recovered delivery" value={a.costPerRecovered.available ? money(a.costPerRecovered.valuePaise) : "Not measurable"} sub={a.costPerRecovered.note} />
        <Stat label="Recovered after contact" value={num(a.costPerRecovered.recovered)} sub="Delivered after an NDR, with evidence the customer was reached" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Why deliveries failed" subtitle="NDR reasons opened in this period" actions={<Freshness at={a.generatedAt} />} />
          <div className="px-4 py-3"><HBars items={a.reasons.map((r) => ({ label: NDR_REASON[r.reason] ?? r.reason, value: r.count, href: `/ndr?queue=all&reason=${r.reason}` }))} /></div>
        </Panel>
        <Panel>
          <PanelHeader title="RTO by reason" subtitle="Share of closed cases that went back to origin" />
          <Table head={["Reason", "Closed", "RTO", "RTO rate"]} rows={a.rtoByReason.map((r) => [NDR_REASON[r.reason] ?? r.reason, num(r.closed), num(r.rto), ratio(r.rtoRate, r.rto, r.closed)])} />
        </Panel>
      </div>
      <Panel>
        <PanelHeader title="By carrier" subtitle="Recovery and RTO rates use closed cases as the denominator" />
        <Table head={["Carrier", "Cases", "Still open", "Recovered", "Recovery rate", "RTO rate"]}
          rows={a.byCarrier.map((c) => [CARRIERS[c.carrier] ?? c.carrier, num(c.cases), num(c.open), num(c.recovered), ratio(c.recoveryRate, c.recovered, c.closed), ratio(c.rtoRate, c.rto, c.closed)])} />
      </Panel>
    </div>
  );
}

function LanguagesTab({ range }: { range: string }) {
  const q = useQuery({ queryKey: ["dashboard", "languages", range], queryFn: () => api<Languages>("/dashboard/languages", { query: { range } }) });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!q.data) return <Skeleton className="h-64 w-full" />;
  const l = q.data;
  const confirmed = Object.fromEntries(l.confirmed.map((x) => [x.language, x.count]));
  const langs = Array.from(new Set([...l.inferred.map((x) => x.language), ...l.confirmed.map((x) => x.language)]));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Calls with a language switch" value={pct(l.calls.switchRate)} sub={`${num(l.calls.withSwitch)} of ${num(l.calls.completed)} answered calls`} />
        <Stat label="Finished in starting language" value={num(l.calls.completedInStartLanguage)} sub={`of ${num(l.calls.completed)} answered calls`} />
        <Stat label="Code-mixed customer turns" value={num(l.calls.codeMixedTurns)} sub="e.g. Hinglish, Tanglish" />
        <Stat label="Unsupported or not understood" value={num(l.calls.unsupportedLanguage + l.calls.unrecognised)} sub={`${num(l.calls.unsupportedLanguage)} unsupported language · ${num(l.calls.unrecognised)} unresolved or silent`} />
      </div>
      <Notice>{l.intentAccuracy.note}.</Notice>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Predicted vs confirmed language" subtitle="Predicted from address and history before contact; confirmed by the customer" actions={<Freshness at={l.generatedAt} />} />
          <Table head={["Language", "Predicted", "Confirmed"]} rows={langs.map((x) => [lang(x), num(l.inferred.find((i) => i.language === x)?.count ?? 0), num(confirmed[x] ?? 0)])} />
        </Panel>
        <Panel>
          <PanelHeader title="Detected in customer replies" subtitle="Language detected on each turn, with average detector confidence" />
          <Table head={["Language", "Voice turns", "Confidence", "Messages", "Confidence"]}
            rows={l.detectedPerTurn.map((d) => [lang(d.language), num(d.voiceTurns ?? 0), d.avgConfidence ? pct(d.avgConfidence, 0) : "—", num(d.messages ?? 0), d.messageAvgConfidence ? pct(d.messageAvgConfidence, 0) : "—"])} />
        </Panel>
        <Panel>
          <PanelHeader title="Recovery by language" subtitle="Closed cases, by confirmed (else predicted) language" />
          <Table head={["Language", "Closed", "Recovered", "Recovery rate"]} rows={l.recoveryByLanguage.map((r) => [lang(r.language), num(r.closed), num(r.recovered), ratio(r.recoveryRate, r.recovered, r.closed)])} />
        </Panel>
        <Panel>
          <PanelHeader title="Clarification needed" subtitle="Share of extracted replies that were not clearly valid" />
          <Table head={["Language", "Replies analysed", "Needed clarification"]} rows={l.clarificationByLanguage.map((c) => [lang(c.language), num(c.extractions), c.clarificationRate === null ? "—" : pct(c.clarificationRate)])} />
        </Panel>
        <Panel className="xl:col-span-2">
          <PanelHeader title="Answered calls by final language" />
          <Table head={["Language", "Calls", "Average duration", "Reported cost"]} rows={l.byLanguageCalls.map((c) => [lang(c.language), num(c.calls), c.avgDurationSeconds === null ? "—" : `${Math.round(c.avgDurationSeconds)} s`, c.costPaise === null ? "Not reported" : money(c.costPaise)])} />
        </Panel>
      </div>
    </div>
  );
}

function HealthTab({ range }: { range: string }) {
  const q = useQuery({ queryKey: ["dashboard", "agent-health", range], queryFn: () => api<Health>("/dashboard/agent-health", { query: { range } }) });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!q.data) return <Skeleton className="h-64 w-full" />;
  const h = q.data;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Agent runs" value={num(h.runs)} sub={`${num(h.failedRuns)} failed · ${num(h.runsWithFailedSteps)} with a failed step`} />
        <Stat label="Structured-output fallbacks" value={num(h.structuredOutputFallbacks)} sub={`of ${num(h.extractions)} intent extractions fell back to rules`} />
        <Stat label="Jobs retried" value={num(h.retriedJobs)} sub="Succeeded or still retrying after a transient error" />
        <Stat label="Dead-lettered jobs" value={num(h.deadJobs)} sub="Exhausted retries; see Integrations" />
      </div>
      <Panel>
        <PanelHeader title="Tool calls" subtitle="Every typed tool the agents may use" actions={<Freshness at={h.generatedAt} />} />
        <Table head={["Tool", "Calls", "Failed", "Failure rate", "Average latency"]}
          rows={h.tools.map((t) => [<span key={t.tool} className="font-mono text-[12px]">{t.tool}</span>, num(t.calls), num(t.failed), ratio(t.failureRate, t.failed, t.calls), t.avgMs === null ? "—" : `${t.avgMs} ms`])} />
      </Panel>
    </div>
  );
}
