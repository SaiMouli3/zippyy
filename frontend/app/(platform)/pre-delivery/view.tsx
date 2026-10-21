"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { usePoll } from "@/components/platform/providers";
import {
  Badge, cx, Empty, ErrorBox, Freshness, LangTag, Mono, PageHeader, Pagination, Panel, SkeletonRows, StatusBadge, Tabs, Timestamp,
} from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { dateOnly, num, pct, window_ } from "@/lib/platform/format";
import { useUrlState } from "@/lib/platform/hooks";
import { CARRIERS, SHIPMENT_STATUS, title } from "@/lib/platform/labels";

interface Row {
  taskId: string; shipmentId: string; awb: string | null; carrier: string | null; shipmentStatus: string | null; orderRef: string | null;
  paymentMode: string | null; customerName: string | null; language: string | null; status: string; waitingFor: string | null;
  outcome: string | null; needsAttention: boolean; preference: { date: string | null; window: string | null; status: string } | null;
  startedAt: string; updatedAt: string;
}
interface Resp extends Page<Row> { stats7d: { started: number; confirmedAvailable: number; rescheduledOrNoted: number; responseRate: number | null } }

const DEFAULTS = { view: "all", page: "1" };
const VIEW_QUERY: Record<string, Record<string, string>> = {
  all: {}, active: { status: "active,waiting" }, attention: { attention: "true" }, done: { status: "completed" },
};
const TASK_TONE: Record<string, { label: string; tone: "info" | "ok" | "warn" | "muted" | "danger" }> = {
  active: { label: "Working", tone: "info" }, waiting: { label: "Waiting", tone: "info" }, completed: { label: "Done", tone: "muted" },
  escalated: { label: "With operator", tone: "danger" }, cancelled: { label: "Stopped", tone: "muted" }, superseded: { label: "Superseded", tone: "muted" },
  failed: { label: "Failed", tone: "danger" },
};
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function PreDeliveryView() {
  const poll = usePoll();
  const { state: f, set } = useUrlState(DEFAULTS);
  const query = { ...VIEW_QUERY[f.view], page: f.page, pageSize: 50 };
  const list = useQuery({ queryKey: ["pre-delivery", query], queryFn: () => api<Resp>("/pre-delivery", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const st = list.data?.stats7d;
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Pre-delivery confirmation"
        description="Before a parcel goes out for delivery, the agent asks the customer on WhatsApp (and by voice if needed) whether they will be available, in their language."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { l: "Workflows started", v: st ? num(st.started) : "…" },
          { l: "Confirmed available", v: st ? num(st.confirmedAvailable) : "…" },
          { l: "Rescheduled or noted", v: st ? num(st.rescheduledOrNoted) : "…" },
          { l: "Response rate", v: st ? (st.responseRate === null ? "No data" : pct(st.responseRate)) : "…", n: "(confirmed + rescheduled) ÷ started" },
        ].map((k) => (
          <div key={k.l} className="rounded-[10px] border border-line bg-surface p-3.5 shadow-panel" title={k.n}>
            <p className="text-[12px] font-medium text-fg-muted">{k.l} <span className="text-fg-subtle">· 7 days</span></p>
            <p className="num mt-1.5 font-heading text-[22px] font-bold text-fg-strong">{k.v}</p>
          </div>
        ))}
      </div>
      <Panel>
        <Tabs className="px-2" value={f.view} onChange={(view) => set({ view })}
          tabs={[{ id: "all", label: "All" }, { id: "active", label: "In progress" }, { id: "attention", label: "Needs attention" }, { id: "done", label: "Completed" }]
            .map((t) => ({ ...t, count: t.id === f.view && list.data ? total : null }))} />
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={8} /> : total === 0 ? (
          <Empty title="Nothing here">Workflows start automatically when a carrier marks a shipment out for delivery or dispatch is imminent.</Empty>
        ) : (
          <div className={cx("overflow-x-auto scrollbar-thin", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[960px] text-[12.5px]">
              <thead className="bg-zy-paper">
                <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                  {["Shipment", "Customer", "Language", "Carrier", "Shipment status", "Workflow", "Outcome", "Preference", "Started"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data!.items.map((r) => (
                  <tr key={r.taskId} className="hover:bg-zy-paper">
                    <td className="whitespace-nowrap px-3 py-2"><Link prefetch={false} href={`/shipments/${r.shipmentId}`} className="font-medium text-fg-strong hover:underline">{r.orderRef ?? "—"}</Link><div><Mono className="text-2xs text-fg-muted">{r.awb}</Mono></div></td>
                    <td className="whitespace-nowrap px-3 py-2">{r.customerName ?? "—"}<div className="text-2xs text-fg-muted">{r.paymentMode}</div></td>
                    <td className="px-3 py-2"><LangTag code={r.language} /></td>
                    <td className="whitespace-nowrap px-3 py-2">{r.carrier ? CARRIERS[r.carrier] ?? r.carrier : "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2"><StatusBadge map={SHIPMENT_STATUS} value={r.shipmentStatus} /></td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <StatusBadge map={TASK_TONE} value={r.status} />
                      {r.waitingFor && ["active", "waiting"].includes(r.status) && <div className="text-2xs text-fg-muted">for {title(r.waitingFor)}</div>}
                    </td>
                    <td className="max-w-[260px] px-3 py-2">{r.outcome ? sentence(r.outcome) : <span className="text-fg-subtle">—</span>}{r.needsAttention && <Badge tone="warn" className="ml-2">Attention</Badge>}</td>
                    <td className="whitespace-nowrap px-3 py-2">{r.preference ? <>{r.preference.date ? dateOnly(r.preference.date) : "—"}{r.preference.window ? ` · ${window_(r.preference.window)}` : ""}<div className="text-2xs text-fg-muted">{title(r.preference.status)}</div></> : <span className="text-fg-subtle">—</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={r.startedAt} /></td>
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
