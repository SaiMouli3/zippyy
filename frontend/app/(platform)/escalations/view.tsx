"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { MultiSelect, opts } from "@/components/platform/filters";
import { usePoll } from "@/components/platform/providers";
import {
  Badge, cx, Empty, ErrorBox, Freshness, Mono, PageHeader, Pagination, Panel, SkeletonRows, SlaCell, StatusBadge, Tabs, Timestamp,
} from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { useUrlState } from "@/lib/platform/hooks";
import { CARRIERS, ESC_PRIORITY, ESC_REASON, NDR_REASON, title } from "@/lib/platform/labels";
import type { EscalationRow } from "@/lib/platform/types";

const DEFAULTS = { view: "open", priority: "", page: "1" };
const VIEWS: Record<string, { status: string; mine?: boolean }> = {
  open: { status: "open,assigned" }, mine: { status: "open,assigned", mine: true }, resolved: { status: "resolved" }, all: { status: "open,assigned,resolved" },
};

export function EscalationsView() {
  const poll = usePoll();
  const router = useRouter();
  const { state: f, set } = useUrlState(DEFAULTS);
  const v = VIEWS[f.view] ?? VIEWS.open;
  const query = { status: v.status, mine: v.mine ? "true" : undefined, priority: f.priority, page: f.page, pageSize: 50 };
  const list = useQuery({ queryKey: ["escalations", query], queryFn: () => api<Page<EscalationRow>>("/escalations", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Escalations" description="Cases the agent handed to a person: approvals, unclear replies, carrier problems and restricted contacts. Most urgent first."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <Panel>
        <Tabs className="px-2" value={f.view} onChange={(view) => set({ view })}
          tabs={[{ id: "open", label: "Open" }, { id: "mine", label: "Assigned to me" }, { id: "resolved", label: "Resolved" }, { id: "all", label: "All" }]
            .map((t) => ({ ...t, count: t.id === f.view && list.data ? total : null }))} />
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <MultiSelect label="Priority" value={f.priority} onChange={(priority) => set({ priority })} options={opts(ESC_PRIORITY)} />
        </div>
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={8} /> : total === 0 ? (
          <Empty title={f.view === "resolved" ? "Nothing resolved yet" : "No escalations waiting"}>
            {f.view === "mine" ? "Nothing is assigned to you." : "When the agent needs a decision it lands here with the full context."}
          </Empty>
        ) : (
          <div className={cx("overflow-x-auto scrollbar-thin", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[980px] text-[12.5px]">
              <thead className="bg-zy-paper">
                <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                  {["Escalation", "Priority", "Why", "Case", "Customer", "Carrier", "Assignee", "Respond by", "Opened"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data!.items.map((e) => (
                  <tr key={e.id} className="cursor-pointer hover:bg-zy-paper" onClick={(ev) => { if (!(ev.target as HTMLElement).closest("a")) router.push(`/escalations/${e.id}`); }}>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      <Link prefetch={false} href={`/escalations/${e.id}`} className="font-mono text-[12px] font-medium text-fg-strong hover:text-zy-brand hover:underline">{e.code}</Link>
                      {e.pendingDecisionId && <Badge tone="warn" dot={false} className="ml-2">Needs approval</Badge>}
                      {e.supervisorRequested && <Badge tone="info" dot={false} className="ml-1">Supervisor</Badge>}
                    </td>
                    <td className="px-3 py-2.5"><StatusBadge map={ESC_PRIORITY} value={e.priority} /></td>
                    <td className="max-w-[300px] px-3 py-2.5">
                      <div className="font-medium text-fg-strong">{ESC_REASON[e.reason] ?? title(e.reason)}</div>
                      <div className="truncate text-2xs text-fg-muted">{e.summary}</div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      {e.ndrCode ? <Link prefetch={false} href={`/ndr/${e.ndrCaseId}`} className="font-mono text-[12px] hover:underline">{e.ndrCode}</Link> : "—"}
                      <div className="text-2xs text-fg-muted">{e.ndrReason ? NDR_REASON[e.ndrReason] ?? e.ndrReason : ""}</div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">{e.customerName ?? "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{e.carrier ? CARRIERS[e.carrier] ?? e.carrier : "—"}<div><Mono className="text-2xs text-fg-muted">{e.awb}</Mono></div></td>
                    <td className="whitespace-nowrap px-3 py-2.5">{e.assigneeName ?? <span className="text-fg-subtle">Unassigned</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{e.status === "resolved" ? <span className="text-fg-muted">Resolved <Timestamp iso={e.resolvedAt} /></span> : <SlaCell iso={e.slaDueAt} />}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-fg-muted"><Timestamp iso={e.createdAt} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > 0 && <Pagination page={Number(f.page)} pageSize={50} total={total} onPage={(p) => set({ page: String(p) }, { resetPage: false })} />}
      </Panel>
    </>
  );
}
