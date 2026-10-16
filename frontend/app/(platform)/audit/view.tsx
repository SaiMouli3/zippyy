"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { SingleSelect } from "@/components/platform/filters";
import { useSession } from "@/components/platform/providers";
import { Badge, cx, Empty, ErrorBox, Freshness, Mono, PageHeader, Pagination, Panel, SkeletonRows, Timestamp } from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { useUrlState } from "@/lib/platform/hooks";
import { title } from "@/lib/platform/labels";

interface Entry {
  id: string; at: string; actorType: string; actorId: string | null; actor: string | null; entityType: string; entityId: string;
  action: string; before: unknown; after: unknown; reason: string | null; requestId: string | null;
}
const DEFAULTS = { actorType: "", entityType: "", action: "", page: "1" };
const ENTITIES = ["ndr_case", "escalation", "rule_decision", "carrier_action", "customer", "voice_call", "policy_version", "merchant_settings", "api_key", "user", "agent_task", "agent_run", "delivery_preference"];
const ACTIONS = ["auth.", "pii.", "decision.", "escalation.", "agent_config.", "contact_policy.", "settings.", "api_key.", "ndr.", "transcript.", "preference."];
const ACTOR_TONE: Record<string, "info" | "brand" | "neutral" | "warn"> = { user: "info", agent: "brand", system: "neutral", api_key: "warn" };

export function AuditView() {
  const { can } = useSession();
  const { state: f, set } = useUrlState(DEFAULTS);
  const [open, setOpen] = useState<string | null>(null);
  const query = { ...f, pageSize: 50 };
  const list = useQuery({ queryKey: ["audit", query], queryFn: () => api<Page<Entry>>("/audit-logs", { query }), placeholderData: keepPreviousData, enabled: can("audit.read") });
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Audit log" description="Append-only record of who did what: sign-ins, contact-detail reveals, approvals, policy changes, agent actions and API key use. Entries cannot be edited or deleted."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <SingleSelect label="Actor" value={f.actorType} onChange={(actorType) => set({ actorType })} options={[{ value: "user", label: "People" }, { value: "agent", label: "Agents" }, { value: "system", label: "System" }, { value: "api_key", label: "API keys" }]} />
          <SingleSelect label="Record" value={f.entityType} onChange={(entityType) => set({ entityType })} options={ENTITIES.map((e) => ({ value: e, label: title(e) }))} />
          <SingleSelect label="Action" value={f.action} onChange={(action) => set({ action })} options={ACTIONS.map((a) => ({ value: a, label: title(a.replace(".", "")) }))} />
        </div>
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={10} /> : total === 0 ? <Empty title="No entries match" /> : (
          <div className={cx("overflow-x-auto scrollbar-thin", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[900px] text-[12.5px]">
              <thead className="bg-zy-paper">
                <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                  {["", "When", "Who", "Action", "Record", "Reason", "Request"].map((h, i) => <th key={i} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data!.items.map((e) => {
                  const hasDiff = e.before !== null || e.after !== null;
                  return (
                    <Fragment key={e.id}>
                      <tr className={cx(hasDiff && "cursor-pointer hover:bg-zy-paper")} onClick={() => hasDiff && setOpen(open === e.id ? null : e.id)}>
                        <td className="w-6 pl-3">{hasDiff ? (open === e.id ? <ChevronDown className="h-3.5 w-3.5 text-fg-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-fg-muted" />) : null}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={e.at} mode="absolute" /></td>
                        <td className="whitespace-nowrap px-3 py-2"><Badge tone={ACTOR_TONE[e.actorType] ?? "neutral"} dot={false}>{title(e.actorType)}</Badge> <span className="ml-1">{e.actor ?? e.actorId ?? "—"}</span></td>
                        <td className="whitespace-nowrap px-3 py-2"><Mono>{e.action}</Mono></td>
                        <td className="whitespace-nowrap px-3 py-2">{title(e.entityType)} <Mono className="text-2xs text-fg-muted">…{e.entityId.slice(-8)}</Mono></td>
                        <td className="max-w-[320px] truncate px-3 py-2 text-fg-muted" title={e.reason ?? undefined}>{e.reason ?? "—"}</td>
                        <td className="whitespace-nowrap px-3 py-2"><Mono className="text-2xs text-fg-subtle">{e.requestId ?? "—"}</Mono></td>
                      </tr>
                      {open === e.id && (
                        <tr><td colSpan={7} className="bg-zy-paper px-4 py-3">
                          <div className="grid gap-3 md:grid-cols-2">
                            {(["before", "after"] as const).map((k) => (
                              <div key={k}><p className="mb-1 text-2xs font-medium text-fg-muted">{title(k)}</p>
                                <pre className="max-h-60 overflow-auto rounded bg-zy-ink px-2 py-1.5 font-mono text-[11px] leading-4 text-[#E6E6E6] scrollbar-thin">{e[k] === null ? "—" : JSON.stringify(e[k], null, 2)}</pre></div>
                            ))}
                          </div>
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {total > 0 && <Pagination page={Number(f.page)} pageSize={50} total={total} onPage={(p) => set({ page: String(p) }, { resetPage: false })} />}
      </Panel>
    </>
  );
}
