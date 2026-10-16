"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Timeline } from "@/components/platform/case-parts";
import { usePoll } from "@/components/platform/providers";
import { ErrorBox, Freshness, KeyValue, Mono, Panel, PanelHeader, Skeleton, StatusBadge, Timestamp } from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { absolute, dateOnly, money, window_ } from "@/lib/platform/format";
import { CARRIERS, NDR_REASON, NDR_STATUS, SHIPMENT_STATUS, title } from "@/lib/platform/labels";
import type { ShipmentRow, TimelineItem } from "@/lib/platform/types";

export function ShipmentView() {
  const { id } = useParams<{ id: string }>();
  const poll = usePoll();
  const s = useQuery({ queryKey: ["shipments", id], queryFn: () => api<ShipmentRow>(`/shipments/${id}`), refetchInterval: poll });
  const tl = useQuery({ queryKey: ["shipments", id, "timeline"], queryFn: () => api<{ items: TimelineItem[]; generatedAt: string }>(`/shipments/${id}/timeline`), refetchInterval: poll });
  const attempts = useQuery({ queryKey: ["shipments", id, "attempts"], queryFn: () => api<{ items: { attemptNo: number; outcome: string; reason: string | null; courierRemark: string | null; at: string }[] }>(`/shipments/${id}/attempts`) });
  const back = <Link href="/shipments" className="inline-flex items-center gap-1 text-[12.5px] text-fg-muted hover:text-fg-strong"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Shipments</Link>;
  if (s.isError) return <div className="space-y-3">{back}<Panel>{(s.error as ApiError).status === 404 ? <p className="px-6 py-14 text-center text-[13px] text-fg-muted">Shipment not found in this workspace.</p> : <ErrorBox error={s.error} onRetry={() => s.refetch()} />}</Panel></div>;
  if (!s.data) return <div className="space-y-4">{back}<Skeleton className="h-8 w-72" /><Skeleton className="h-80 w-full" /></div>;
  const d = s.data;
  return (
    <div className="space-y-4">
      {back}
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="font-mono text-[20px] font-semibold tracking-tight text-fg-strong">{d.code}</h1>
        <StatusBadge map={SHIPMENT_STATUS} value={d.status} />
        <span className="text-[12.5px] text-fg-muted">{CARRIERS[d.carrier] ?? d.carrier} <Mono className="text-[12px] text-fg-muted">{d.awb}</Mono></span>
        {d.ndrCaseId && <Link href={`/ndr/${d.ndrCaseId}`} className="ml-auto inline-flex items-center gap-2 rounded-md border border-line-strong bg-surface px-3 py-1.5 text-[12.5px] hover:bg-zy-paper">NDR case <Mono>{d.ndrCode}</Mono><StatusBadge map={NDR_STATUS} value={d.ndrStatus} /></Link>}
      </header>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel className="min-w-0">
          <PanelHeader title="Tracking & activity" subtitle="Carrier scans, customer contact, agent decisions and carrier requests in order" actions={<Freshness at={tl.data?.generatedAt} fetching={tl.isFetching} />} />
          <div className="px-4 py-4">{tl.isError ? <ErrorBox error={tl.error} compact /> : tl.data ? <Timeline items={tl.data.items} /> : <Skeleton className="h-60 w-full" />}</div>
        </Panel>
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Order" />
            <div className="px-4 py-3">
              <KeyValue cols={2} items={[
                { k: "Order", v: d.orderRef }, { k: "Payment", v: d.paymentMode === "COD" ? `COD · ${money(d.codAmountPaise)}` : title(d.paymentMode?.toLowerCase()) },
                { k: "Order value", v: money(d.orderValuePaise) }, { k: "Customer", v: d.customerName },
                { k: "Phone", v: <Mono className="text-[12px]">{d.phoneMasked ?? "—"}</Mono> }, { k: "Destination", v: [d.city, d.state, d.pincode].filter(Boolean).join(", ") },
                { k: "Created", v: <Timestamp iso={d.createdAt} mode="absolute" /> }, { k: "ETA", v: d.etaEnd ? absolute(d.etaEnd) : "—" },
                { k: "Delivered", v: d.deliveredAt ? absolute(d.deliveredAt) : "—" }, { k: "Attempts", v: d.attempts },
              ]} />
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Pre-delivery confirmation" />
            <div className="space-y-1.5 px-4 py-3 text-[12.5px]">
              {d.preDelivery ? <>
                <p><span className="text-fg-subtle">Workflow</span> <span className="ml-2 font-medium text-fg-strong">{title(d.preDelivery.status)}</span>{d.preDelivery.outcome && <span className="text-fg-muted"> · {title(d.preDelivery.outcome)}</span>}</p>
                {d.preference ? <p><span className="text-fg-subtle">Preference</span> <span className="ml-2 text-fg-strong">{d.preference.date ? dateOnly(d.preference.date) : "—"}{d.preference.window ? ` · ${window_(d.preference.window)}` : ""}</span> <span className="text-fg-muted">({title(d.preference.status)} via {title(d.preference.channel)})</span></p> : null}
              </> : <p className="text-fg-muted">No pre-delivery workflow ran for this shipment.</p>}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Delivery attempts" />
            {attempts.data?.items.length ? (
              <ol className="divide-y divide-line">
                {attempts.data.items.map((a) => (
                  <li key={a.attemptNo} className="px-4 py-2.5 text-[12.5px]">
                    <div className="flex items-center gap-2"><span className="font-medium text-fg-strong">Attempt {a.attemptNo}</span><span className="text-fg-muted">{title(a.outcome)}</span><span className="ml-auto text-2xs text-fg-muted"><Timestamp iso={a.at} mode="absolute" /></span></div>
                    {(a.reason || a.courierRemark) && <p className="mt-0.5 text-2xs text-fg-muted">{a.reason ? NDR_REASON[a.reason] ?? a.reason : ""}{a.courierRemark ? ` — “${a.courierRemark}”` : ""}</p>}
                  </li>
                ))}
              </ol>
            ) : <p className="px-4 py-4 text-[12.5px] text-fg-muted">{attempts.isLoading ? "Loading…" : "No delivery attempt recorded yet."}</p>}
          </Panel>
        </div>
      </div>
    </div>
  );
}
