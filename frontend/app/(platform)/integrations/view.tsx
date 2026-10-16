"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, MessageCircle, Phone, Truck } from "lucide-react";
import { useState } from "react";

import { usePoll, useSession } from "@/components/platform/providers";
import { Badge, cx, ErrorBox, Freshness, KeyValue, LangTag, Mono, Notice, PageHeader, Panel, PanelHeader, Skeleton, Timestamp } from "@/components/platform/ui";
import { api } from "@/lib/platform/api";
import { num, pct } from "@/lib/platform/format";
import type { Tone } from "@/lib/platform/labels";
import { title } from "@/lib/platform/labels";

interface Stats { calls1h: number; errors1h: number; errorRate1h: number | null; p95LatencyMs: number | null; lastSuccessAt: string | null }
interface Provider extends Stats { id: string; name: string; provider: string; mode: string; state: string; detail: string }
interface CarrierRow extends Stats { code: string; name: string; mode: string; active: boolean; state: string }
interface Integrations {
  providers: Provider[]; carriers: CarrierRow[];
  webhooks: { last24h: Record<string, number>; quarantinedOpen: Record<string, number> };
  jobs: { due: number; scheduled: number; running: number; dead24h: number; oldestDueAt: string | null; lastProcessedAt: string | null; workerHealthy: boolean };
  outbox: { unpublished: number }; environment: { appEnv: string; signatureRequired: boolean }; generatedAt: string;
}
interface Template { id: string; code: string; language: string; version: number; status: string; category: string; providerTemplateName: string | null; body: string }
interface CarrierCaps { code: string; name: string; mode: string; active: boolean; timeoutMs: number; capabilities: Record<string, unknown> }

const STATE: Record<string, { label: string; tone: Tone }> = {
  connected: { label: "Connected", tone: "ok" }, degraded: { label: "Degraded", tone: "warn" }, failing: { label: "Failing", tone: "danger" },
  simulated: { label: "Simulated", tone: "warn" }, not_configured: { label: "Not configured", tone: "muted" },
};
const ICON: Record<string, typeof Bot> = { whatsapp: MessageCircle, voice: Phone, intent: Bot };

export function IntegrationsView() {
  const poll = usePoll();
  const { can } = useSession();
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => api<Integrations>("/integrations"), refetchInterval: poll === false ? 30000 : poll });
  const caps = useQuery({ queryKey: ["integrations", "carriers"], queryFn: () => api<{ items: CarrierCaps[] }>("/merchant/carriers") });
  const templates = useQuery({ queryKey: ["integrations", "templates"], queryFn: () => api<{ items: Template[] }>("/merchant/templates"), enabled: can("policies.read") });
  return (
    <>
      <PageHeader title="Integrations" description="Provider and carrier connections, webhook intake and background processing. Health is measured from real calls in the last hour."
        meta={<Freshness at={q.data?.generatedAt} fetching={q.isFetching} onRefresh={() => q.refetch()} />} />
      {q.isError ? <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel> : !q.data ? <Skeleton className="h-64 w-full" /> : (
        <div className="space-y-4">
          {q.data.environment.appEnv !== "production" && <Notice tone="warn">Environment: <strong>{q.data.environment.appEnv}</strong>. Carrier webhook signatures are {q.data.environment.signatureRequired ? "required" : "not required"}.</Notice>}
          <div className="grid gap-3 lg:grid-cols-3">
            {q.data.providers.map((p) => {
              const Icon = ICON[p.id] ?? Bot;
              const s = STATE[p.state] ?? { label: title(p.state), tone: "neutral" as Tone };
              return (
                <Panel key={p.id} className="p-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zy-paper-2"><Icon className="h-4 w-4 text-fg-strong" aria-hidden /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2"><p className="font-heading text-[14px] font-bold text-fg-strong">{p.name}</p><Badge tone={s.tone}>{s.label}</Badge></div>
                      <p className="mt-0.5 text-2xs text-fg-muted">{p.detail}</p>
                    </div>
                  </div>
                  {p.id !== "intent" && <div className="mt-3 border-t border-line pt-3"><ProviderStats s={p} /></div>}
                </Panel>
              );
            })}
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel>
              <PanelHeader title="Background processing" subtitle="Durable job queue and transactional outbox" />
              <div className="px-4 py-3">
                <div className="mb-3 flex flex-wrap items-center gap-2"><WorkerState jobs={q.data.jobs} /></div>
                <KeyValue cols={3} items={[
                  { k: "Due now", v: num(q.data.jobs.due) }, { k: "Running", v: num(q.data.jobs.running) }, { k: "Scheduled", v: num(q.data.jobs.scheduled) },
                  { k: "Dead-lettered (24 h)", v: <span className={cx(q.data.jobs.dead24h > 0 && "font-semibold text-danger")}>{num(q.data.jobs.dead24h)}</span> },
                  { k: "Oldest due", v: q.data.jobs.oldestDueAt ? <Timestamp iso={q.data.jobs.oldestDueAt} /> : "—" },
                  { k: "Unpublished events", v: num(q.data.outbox.unpublished) },
                ]} />
              </div>
            </Panel>
            <Panel>
              <PanelHeader title="Webhook intake (24 h)" subtitle="Every inbound webhook is stored, de-duplicated and processed; anything that can't be applied safely is quarantined" />
              <div className="grid gap-4 px-4 py-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-fg-subtle">By state</p>
                  {Object.keys(q.data.webhooks.last24h).length ? <ul className="space-y-1 text-[12.5px]">{Object.entries(q.data.webhooks.last24h).map(([k, v]) => <li key={k} className="flex justify-between"><span>{title(k)}</span><span className="num font-medium">{num(v)}</span></li>)}</ul> : <p className="text-[12.5px] text-fg-muted">None received</p>}
                </div>
                <div>
                  <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-fg-subtle">Quarantined, unresolved</p>
                  {Object.keys(q.data.webhooks.quarantinedOpen).length ? <ul className="space-y-1 text-[12.5px]">{Object.entries(q.data.webhooks.quarantinedOpen).map(([k, v]) => <li key={k} className="flex justify-between text-warn"><span>{title(k)}</span><span className="num font-medium">{num(v)}</span></li>)}</ul> : <p className="text-[12.5px] text-fg-muted">Nothing quarantined</p>}
                </div>
              </div>
            </Panel>
          </div>

          <Panel>
            <PanelHeader title="Carriers" subtitle="NDR action APIs and tracking webhooks" />
            <div className="divide-y divide-line">
              {q.data.carriers.map((c) => {
                const s = STATE[c.state] ?? { label: title(c.state), tone: "neutral" as Tone };
                const cap = caps.data?.items.find((x) => x.code === c.code);
                return (
                  <div key={c.code} className="grid gap-3 px-4 py-3 md:grid-cols-[220px_1fr_1fr]">
                    <div className="flex items-start gap-2">
                      <Truck className="mt-0.5 h-4 w-4 text-fg-muted" aria-hidden />
                      <div><p className="text-[13px] font-medium text-fg-strong">{c.name}</p>
                        <div className="mt-0.5 flex flex-wrap gap-1.5"><Badge tone={s.tone}>{s.label}</Badge>{!c.active && <Badge tone="muted">Inactive</Badge>}</div></div>
                    </div>
                    <ProviderStats s={c} />
                    <div className="text-2xs text-fg-muted">
                      {cap ? <>
                        <p className="mb-1">Timeout {num(cap.timeoutMs)} ms · capabilities</p>
                        <div className="flex flex-wrap gap-1">{Object.keys(cap.capabilities).map((k) => <span key={k} className="rounded border border-line px-1.5 py-px font-mono text-[10.5px] text-fg">{k}</span>)}</div>
                      </> : caps.isLoading ? "…" : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>

          {can("policies.read") && <Templates q={templates} />}
        </div>
      )}
    </>
  );
}

/** Derived only from what the queue proves: due jobs waiting too long means stalled; recent completions mean processing. */
function WorkerState({ jobs }: { jobs: Integrations["jobs"] }) {
  const now = Date.now();
  const oldestWait = jobs.oldestDueAt ? (now - new Date(jobs.oldestDueAt).getTime()) / 60000 : 0;
  const lastAgo = jobs.lastProcessedAt ? (now - new Date(jobs.lastProcessedAt).getTime()) / 60000 : null;
  const last = <span className="text-2xs text-fg-muted">Last job finished {jobs.lastProcessedAt ? <Timestamp iso={jobs.lastProcessedAt} /> : "never"}</span>;
  if (jobs.due > 0 && oldestWait > 2) return <><Badge tone="danger">Stalled — {num(jobs.due)} due jobs waiting</Badge>{last}</>;
  if (lastAgo !== null && lastAgo < 10) return <><Badge tone="ok">Processing</Badge>{last}</>;
  return <><Badge tone="neutral">Idle — nothing due</Badge>{last}{jobs.scheduled > 0 && <span className="text-2xs text-fg-muted">· confirms activity when the next scheduled job falls due</span>}</>;
}

function ProviderStats({ s }: { s: Stats }) {
  return (
    <dl className="grid grid-cols-3 gap-2 text-[12px]">
      <div><dt className="text-2xs text-fg-subtle">Calls (1 h)</dt><dd className="num font-medium text-fg-strong">{num(s.calls1h)}</dd></div>
      <div><dt className="text-2xs text-fg-subtle">Error rate</dt><dd className={cx("num font-medium", (s.errorRate1h ?? 0) > 0.1 ? "text-danger" : "text-fg-strong")}>{s.calls1h ? pct(s.errorRate1h) : "—"}</dd></div>
      <div><dt className="text-2xs text-fg-subtle">p95 latency</dt><dd className="num font-medium text-fg-strong">{s.p95LatencyMs !== null ? `${s.p95LatencyMs} ms` : "—"}</dd></div>
      <div className="col-span-3"><dt className="inline text-2xs text-fg-subtle">Last success </dt><dd className="inline text-2xs text-fg">{s.lastSuccessAt ? <Timestamp iso={s.lastSuccessAt} /> : "none recorded"}</dd></div>
    </dl>
  );
}

function Templates({ q }: { q: { data?: { items: Template[] }; isError: boolean; error: unknown } }) {
  const [open, setOpen] = useState<string | null>(null);
  const groups = new Map<string, Template[]>();
  q.data?.items.forEach((t) => groups.set(t.code, [...(groups.get(t.code) ?? []), t]));
  return (
    <Panel>
      <PanelHeader title="WhatsApp message templates" subtitle="Business-initiated messages must use an approved template, in the customer's language" />
      {q.isError ? <ErrorBox error={q.error} compact /> : !q.data ? <Skeleton className="m-4 h-24" /> : !groups.size ? <p className="px-4 py-6 text-[12.5px] text-fg-muted">No templates registered.</p> : (
        <ul className="divide-y divide-line">
          {Array.from(groups.entries()).map(([code, ts]) => {
            const approved = ts.filter((t) => t.status === "approved").length;
            return (
              <li key={code}>
                <button onClick={() => setOpen(open === code ? null : code)} aria-expanded={open === code} className="flex w-full flex-wrap items-center gap-2 px-4 py-2.5 text-left text-[12.5px] hover:bg-zy-paper">
                  <Mono>{code}</Mono><span className="text-2xs text-fg-muted">v{Math.max(...ts.map((t) => t.version))} · {title(ts[0].category.toLowerCase())}</span>
                  <span className="flex flex-wrap gap-1">{ts.map((t) => <LangTag key={t.id} code={t.language} confirmed={t.status === "approved"} />)}</span>
                  <Badge tone={approved === ts.length ? "ok" : "warn"} className="ml-auto">{approved === ts.length ? "All approved" : `${approved} of ${ts.length} approved`}</Badge>
                </button>
                {open === code && (
                  <ul className="divide-y divide-line border-t border-line bg-zy-paper">
                    {ts.map((t) => (
                      <li key={t.id} className="flex gap-3 px-4 py-2 text-[12.5px]">
                        <LangTag code={t.language} confirmed /><p className="min-w-0 flex-1 whitespace-pre-wrap text-fg-strong">{t.body}</p>
                        <Badge tone={t.status === "approved" ? "ok" : t.status === "rejected" ? "danger" : "warn"}>{title(t.status)}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
