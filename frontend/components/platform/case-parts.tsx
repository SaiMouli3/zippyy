"use client";

import {
  Bot, ChevronDown, ChevronRight, Headphones, Languages, MessageCircle, PackageSearch, Scale, ShieldAlert, Truck, UserRound,
} from "lucide-react";
import Link from "next/link";
import { ReactNode, useState } from "react";

import { Badge, cx, LangTag, Mono, StatusBadge, Timestamp, Tooltip } from "@/components/platform/ui";
import { absolute, dateOnly, duration, pct, window_ } from "@/lib/platform/format";
import { ACTION_STATUS, CALL_RESULT, CALL_STATUS, LANG, MESSAGE_STATUS, STEP_STATUS, title, VERDICT } from "@/lib/platform/labels";
import type { CallItem, CarrierActionT, Decision, MessageItem, Run, Step, Thread, TimelineItem } from "@/lib/platform/types";

// ------------------------------------------------------------------ timeline
const CAT: Record<TimelineItem["category"], { icon: typeof Truck; label: string; cls: string }> = {
  shipment: { icon: Truck, label: "Shipment", cls: "bg-zy-paper-2 text-fg" },
  communication: { icon: MessageCircle, label: "Customer contact", cls: "bg-info-soft text-info" },
  ai: { icon: Bot, label: "Agent & rules", cls: "bg-zy-brand-soft text-zy-brand" },
  carrier: { icon: PackageSearch, label: "Carrier request", cls: "bg-warn-soft text-warn" },
  admin: { icon: UserRound, label: "Operator", cls: "bg-ok-soft text-ok" },
};
export const TIMELINE_CATS = Object.entries(CAT).map(([id, v]) => ({ id, label: v.label }));

function resultBadge(item: TimelineItem) {
  const r = item.result;
  if (!r) return null;
  if (item.category === "carrier") return <StatusBadge map={ACTION_STATUS} value={r} />;
  if (item.type.startsWith("message.")) return <StatusBadge map={MESSAGE_STATUS} value={r} />;
  if (item.type.startsWith("call.") && item.type !== "call.language_switch") return <StatusBadge map={CALL_STATUS} value={r} />;
  if (item.type === "ai.rules_evaluated") return <StatusBadge map={VERDICT} value={r} />;
  if (item.type === "call.language_switch") return <LangTag code={r} confirmed />;
  return <Badge tone="neutral" dot={false}>{title(r.toLowerCase())}</Badge>;
}

function DetailList({ detail }: { detail: Record<string, unknown> }) {
  const entries = Object.entries(detail).filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length));
  if (!entries.length) return <p className="text-2xs text-fg-subtle">No further detail recorded.</p>;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-2xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg-subtle">{title(k.replace(/([A-Z])/g, " $1").toLowerCase())}</dt>
          <dd className="min-w-0 break-words text-fg">{typeof v === "object" ? <code className="font-mono">{JSON.stringify(v)}</code> : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ol className="relative">
      {items.map((it, i) => {
        const c = CAT[it.category];
        const Icon = c.icon;
        const expanded = open === it.id;
        return (
          <li key={it.id + i} className="relative flex gap-3 pb-3 last:pb-0">
            {i < items.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-20px)] w-px bg-line" />}
            <span className={cx("relative z-[1] mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", c.cls)} title={c.label}>
              <Icon className="h-3.5 w-3.5" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <button onClick={() => setOpen(expanded ? null : it.id)} aria-expanded={expanded}
                className="group flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-1.5 py-1 text-left hover:bg-zy-paper">
                <span className="text-[13px] font-medium text-fg-strong">{it.title}</span>
                {resultBadge(it)}
                <span className="ml-auto flex items-center gap-2 text-2xs text-fg-muted">
                  <span className="hidden sm:inline">{it.source}</span>
                  <Timestamp iso={it.at} mode="absolute" />
                  {expanded ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-100" aria-hidden />}
                </span>
              </button>
              {expanded && (
                <div className="ml-1.5 mt-1 rounded-md border border-line bg-zy-paper px-3 py-2">
                  <DetailList detail={{ ...it.detail, actor: it.actor, source: it.source, recorded: absolute(it.at, true), correlation: it.correlationId }} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ conversation thread
export function ThreadView({ thread, caseLink = false }: { thread: Thread; caseLink?: boolean }) {
  if (!thread.items.length) return <p className="py-10 text-center text-[13px] text-fg-muted">No messages or calls for this shipment yet.</p>;
  return (
    <ol className="space-y-3">
      {thread.items.map((it) => <li key={it.kind + it.id}>{it.kind === "message" ? <Bubble m={it} caseLink={caseLink} /> : <CallCard c={it} />}</li>)}
    </ol>
  );
}

function Bubble({ m, caseLink }: { m: MessageItem; caseLink: boolean }) {
  const inbound = m.direction === "inbound";
  return (
    <div className={cx("flex", inbound ? "justify-start" : "justify-end")}>
      <div className={cx("max-w-[85%] rounded-xl border px-3 py-2 sm:max-w-[70%]", inbound ? "rounded-tl-sm border-line bg-surface" : "rounded-tr-sm border-[#D9EFD9] bg-[#EEF8EE]")}>
        <div className="mb-1 flex flex-wrap items-center gap-1.5 text-2xs text-fg-muted">
          <span className="font-medium text-fg">{inbound ? "Customer" : m.sender === "agent" ? "Zippyy agent" : "System"}</span>
          <span>· WhatsApp</span>
          {m.templateCode && <Tooltip text={`Approved template ${m.templateCode} v${m.templateVersion}`}><span className="rounded bg-white/70 px-1 font-mono">{m.templateCode}</span></Tooltip>}
          <LangTag code={m.language} confirmed={inbound} />
          {m.languageConfidence !== null && inbound && <span>{pct(m.languageConfidence, 0)}</span>}
        </div>
        <p className="whitespace-pre-wrap break-words text-[13px] leading-5 text-fg-strong">{m.body}</p>
        <div className="mt-1.5 flex flex-wrap items-center justify-end gap-2 text-2xs text-fg-muted">
          {m.intent && (
            <Tooltip text={`Extracted (${m.intent.validation ?? "—"}): ${m.intent.intent}${m.intent.date ? ` · ${m.intent.date}` : ""}${m.intent.window ? ` ${m.intent.window}` : ""}`}>
              <span className="rounded border border-dashed border-zy-brand/40 px-1 text-zy-brand">AI: {title(m.intent.intent)} · {pct(m.intent.confidence, 0)}</span>
            </Tooltip>
          )}
          {!inbound && <StatusBadge map={MESSAGE_STATUS} value={m.status} />}
          {m.failureReason && <span className="text-danger">{m.failureReason}</span>}
          <Timestamp iso={m.at} mode="absolute" />
          {caseLink && m.ndrCaseId && <Link href={`/ndr/${m.ndrCaseId}`} className="text-zy-brand hover:underline">Case</Link>}
        </div>
      </div>
    </div>
  );
}

function CallCard({ c }: { c: CallItem }) {
  return (
    <div className="mx-auto max-w-[92%] rounded-xl border border-line bg-zy-paper px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <Headphones className="h-4 w-4 text-fg-muted" aria-hidden />
        <span className="font-medium text-fg-strong">Voice call {c.code}</span>
        <span className="text-fg-muted">{title(c.purpose)} · attempt {c.attemptNo}</span>
        <StatusBadge map={CALL_STATUS} value={c.status} />
        {c.result && <StatusBadge map={CALL_RESULT} value={c.result} />}
        <span className="ml-auto text-2xs text-fg-muted"><Timestamp iso={c.startedAt ?? c.at} mode="absolute" /></span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-fg-muted">
        <span>Duration {duration(c.durationSeconds)}</span>
        <span className="inline-flex items-center gap-1"><Languages className="h-3 w-3" aria-hidden />
          <LangTag code={c.startLanguage} confirmed={false} />{c.finalLanguage && c.finalLanguage !== c.startLanguage && <>→ <LangTag code={c.finalLanguage} confirmed /></>}
          {c.languageSwitchCount > 0 && <span>({c.languageSwitchCount} switch{c.languageSwitchCount > 1 ? "es" : ""})</span>}
        </span>
        {c.intent && <span className="text-zy-brand">AI: {title(c.intent.intent)} · {pct(c.intent.confidence, 0)}</span>}
        {c.errorMessage && <span className="text-danger">{c.errorMessage}</span>}
        <Link href={`/calls/${c.id}`} className="ml-auto font-medium text-zy-brand hover:underline">{c.transcriptAvailable ? "Open transcript" : "Call details"}</Link>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ agent inspector
export function RunList({ runs }: { runs: Run[] }) {
  const [open, setOpen] = useState<string | null>(runs.find((r) => r.hasFailures)?.id ?? null);
  if (!runs.length) return <p className="py-10 text-center text-[13px] text-fg-muted">The agent has not run for this case yet.</p>;
  return (
    <ul className="divide-y divide-line rounded-md border border-line">
      {runs.map((r) => {
        const expanded = open === r.id;
        return (
          <li key={r.id}>
            <button onClick={() => setOpen(expanded ? null : r.id)} aria-expanded={expanded} className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left hover:bg-zy-paper">
              {expanded ? <ChevronDown className="h-3.5 w-3.5 text-fg-muted" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5 text-fg-muted" aria-hidden />}
              <span className="text-[13px] font-medium text-fg-strong">{title(r.agent)}</span>
              <span className="font-mono text-2xs text-fg-muted">{r.trigger}</span>
              <StatusBadge map={STEP_STATUS} value={r.status} />
              {r.hasFailures && <Badge tone="danger">Failed step</Badge>}
              {r.humanInvolved && <Badge tone="info" dot={false}>Operator involved</Badge>}
              <span className="ml-auto text-2xs text-fg-muted">{r.stepCount} steps · {r.durationMs !== null ? `${r.durationMs} ms` : "running"} · <Timestamp iso={r.startedAt} mode="absolute" /></span>
            </button>
            {expanded && (
              <div className="border-t border-line bg-zy-paper px-3 py-3">
                {r.nextAction && <p className="mb-2 text-2xs text-fg-muted">Next: <span className="font-medium text-fg">{r.nextAction}</span>{r.nextActionAt && <> at {absolute(r.nextActionAt)}</>}</p>}
                {r.error && <p className="mb-2 text-2xs text-danger">{r.error}</p>}
                <Steps steps={r.steps ?? []} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

const KIND_ICON: Record<string, typeof Bot> = { tool_call: Bot, decision: Scale, guard: ShieldAlert, language: Languages };

export function Steps({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!steps.length) return <p className="text-2xs text-fg-subtle">No steps recorded.</p>;
  return (
    <ol className="space-y-1.5">
      {steps.map((s) => {
        const Icon = KIND_ICON[s.kind] ?? Bot;
        const expanded = open === s.id;
        return (
          <li key={s.id} className={cx("rounded-md border bg-surface", ["failed", "timed_out", "rejected"].includes(s.status) ? "border-[#F6C9C4]" : "border-line")}>
            <button onClick={() => setOpen(expanded ? null : s.id)} aria-expanded={expanded} className="flex w-full flex-wrap items-center gap-2 px-2.5 py-1.5 text-left">
              <span className="num w-5 text-2xs text-fg-subtle">{s.seq}</span>
              <Icon className="h-3.5 w-3.5 text-fg-muted" aria-hidden />
              <span className="font-mono text-[12px] text-fg-strong">{s.tool ?? s.kind}</span>
              {s.toolVersion && <span className="text-2xs text-fg-subtle">v{s.toolVersion}</span>}
              <StatusBadge map={STEP_STATUS} value={s.status} />
              {s.policyRule && <Badge tone="brand" dot={false}>{s.policyRule}</Badge>}
              {s.languageBefore && s.languageAfter && s.languageBefore !== s.languageAfter && (
                <span className="inline-flex items-center gap-1 text-2xs text-fg-muted"><LangTag code={s.languageBefore} /> → <LangTag code={s.languageAfter} confirmed /></span>
              )}
              {s.retryCount > 0 && <Badge tone="warn" dot={false}>{s.retryCount} retr{s.retryCount > 1 ? "ies" : "y"}</Badge>}
              <span className="ml-auto text-2xs text-fg-muted">{s.provider ? `${s.provider} · ` : ""}{s.durationMs !== null ? `${s.durationMs} ms` : "—"}</span>
            </button>
            {s.purpose && <p className="px-2.5 pb-1.5 pl-[52px] text-2xs text-fg-muted">{s.purpose}</p>}
            {expanded && (
              <div className="grid gap-2 border-t border-line px-2.5 py-2 md:grid-cols-2">
                <JsonBlock label="Input (sanitized)" value={s.input} />
                <JsonBlock label="Output (sanitized)" value={s.output} />
                {s.error && <p className="text-2xs text-danger md:col-span-2">Error: {s.error}</p>}
                <p className="text-2xs text-fg-subtle md:col-span-2">
                  Started {absolute(s.startedAt, true)}{s.confidence !== null ? ` · confidence ${pct(s.confidence, 0)}` : ""}
                  {s.decisionId ? ` · decision …${s.decisionId.slice(-6)}` : ""}{s.carrierActionId ? ` · carrier action …${s.carrierActionId.slice(-6)}` : ""}
                </p>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-2xs font-medium text-fg-muted">{label}</p>
      <pre className="max-h-48 overflow-auto rounded bg-zy-ink px-2 py-1.5 font-mono text-[11px] leading-4 text-[#E6E6E6] scrollbar-thin">{value === null || value === undefined ? "—" : JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

// ------------------------------------------------------------------ decision & carrier action
export function DecisionView({ d }: { d: Decision | null }) {
  if (!d) return <p className="text-[12.5px] text-fg-muted">The policy engine has not evaluated an action for this case yet.</p>;
  return (
    <div className="space-y-2.5 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge map={VERDICT} value={d.verdict} />
        {d.action && <span className="font-medium text-fg-strong">{title(d.action)}</span>}
        {d.requestedDate && <span className="text-fg-muted">{dateOnly(d.requestedDate)}{d.requestedWindow ? ` · ${window_(d.requestedWindow)}` : ""}</span>}
        {d.approvalStatus && <Badge tone={d.approvalStatus === "approved" ? "ok" : d.approvalStatus === "rejected" ? "danger" : "warn"}>Approval: {d.approvalStatus}</Badge>}
      </div>
      {d.reasons.length > 0 && <ul className="list-disc space-y-0.5 pl-4 text-fg">{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      <ul className="space-y-1">
        {d.rules.map((r) => (
          <li key={r.id} className="flex gap-2"><span className="font-mono text-2xs font-semibold text-zy-brand">{r.id}</span><span className="text-fg-muted">{r.text}</span></li>
        ))}
      </ul>
      <p className="text-2xs text-fg-subtle">Deterministic rules {d.rulesVersion} · <Timestamp iso={d.createdAt} mode="absolute" /></p>
    </div>
  );
}

export function ActionView({ a, extra }: { a: CarrierActionT | null; extra?: ReactNode }) {
  if (!a) return <p className="text-[12.5px] text-fg-muted">No request has been sent to the carrier.</p>;
  const e = ACTION_STATUS[a.status];
  return (
    <div className="space-y-2 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-fg-strong">{title(a.action)}</span>
        <StatusBadge map={ACTION_STATUS} value={a.status} />
        {a.requestedDate && <span className="text-fg-muted">for {dateOnly(a.requestedDate)}{a.requestedWindow ? ` · ${window_(a.requestedWindow)}` : ""}</span>}
      </div>
      {e?.hint && <p className="text-2xs text-fg-muted">{e.hint}</p>}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-2xs">
        <dt className="text-fg-subtle">Carrier reference</dt><dd>{a.carrierReference ? <Mono className="text-2xs">{a.carrierReference}</Mono> : <span className="text-fg-subtle">Not issued</span>}</dd>
        <dt className="text-fg-subtle">Requested</dt><dd><Timestamp iso={a.requestedAt} mode="absolute" /></dd>
        <dt className="text-fg-subtle">Carrier answered</dt><dd>{a.respondedAt ? <Timestamp iso={a.respondedAt} mode="absolute" /> : <span className="text-fg-subtle">No answer yet</span>}</dd>
        <dt className="text-fg-subtle">Verified by tracking</dt><dd>{a.verifiedAt ? <Timestamp iso={a.verifiedAt} mode="absolute" /> : <span className="text-fg-subtle">Not yet</span>}</dd>
        <dt className="text-fg-subtle">Attempts</dt><dd className="num">{a.attempts}</dd>
        {a.rejectionReason && <><dt className="text-fg-subtle">Rejection</dt><dd className="text-danger">{a.rejectionReason}</dd></>}
        {a.lastError && <><dt className="text-fg-subtle">Last error</dt><dd className="text-danger">{a.lastError}</dd></>}
        <dt className="text-fg-subtle">Idempotency key</dt><dd className="truncate"><Mono className="text-2xs text-fg-muted">{a.idempotencyKey}</Mono></dd>
      </dl>
      {extra}
    </div>
  );
}

export const langName = (c: string | null | undefined) => (c ? LANG[c] ?? c : "—");
