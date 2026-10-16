"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MultiSelect, opts, SingleSelect } from "@/components/platform/filters";
import { usePoll } from "@/components/platform/providers";
import { cx, Empty, ErrorBox, Freshness, Input, Mono, PageHeader, Pagination, Panel, SkeletonRows, StatusBadge, Timestamp } from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { money } from "@/lib/platform/format";
import { useDebounced, useUrlState } from "@/lib/platform/hooks";
import { CARRIERS, NDR_STATUS, SHIPMENT_STATUS, title } from "@/lib/platform/labels";
import type { ShipmentRow } from "@/lib/platform/types";

const DEFAULTS = { q: "", status: "", carrier: "", hasNdr: "", page: "1" };

export function ShipmentsView() {
  const poll = usePoll();
  const router = useRouter();
  const { state: f, set } = useUrlState(DEFAULTS);
  const [search, setSearch] = useState(f.q);
  const debounced = useDebounced(search, 350);
  useEffect(() => { if (debounced !== f.q) set({ q: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  const query = { ...f, pageSize: 50 };
  const list = useQuery({ queryKey: ["shipments", query], queryFn: () => api<Page<ShipmentRow>>("/shipments", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Shipments" description="Every shipment Zippyy tracks for this workspace, with its latest carrier status and any NDR case."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search shipments</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="AWB, shipment, order or customer" className="pl-8" />
          </label>
          <MultiSelect label="Status" value={f.status} onChange={(status) => set({ status })} options={opts(SHIPMENT_STATUS)} />
          <MultiSelect label="Carrier" value={f.carrier} onChange={(carrier) => set({ carrier })} options={opts(CARRIERS)} />
          <SingleSelect label="NDR" value={f.hasNdr} onChange={(hasNdr) => set({ hasNdr })} options={[{ value: "true", label: "Has NDR case" }, { value: "false", label: "No NDR" }]} />
        </div>
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={10} /> : total === 0 ? (
          <Empty title="No shipments match">Shipments appear here when your order system sends them to the import API.</Empty>
        ) : (
          <div className={cx("overflow-x-auto scrollbar-thin", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[1000px] text-[12.5px]">
              <thead className="bg-zy-paper">
                <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                  {["Shipment / AWB", "Order", "Customer", "Destination", "Carrier", "Payment", "Status", "Attempts", "NDR", "Last event", "Created"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data!.items.map((s) => (
                  <tr key={s.id} className="cursor-pointer hover:bg-zy-paper" onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) router.push(`/shipments/${s.id}`); }}>
                    <td className="whitespace-nowrap px-3 py-2"><Link href={`/shipments/${s.id}`} className="font-mono text-[12px] font-medium text-fg-strong hover:underline">{s.code}</Link><div><Mono className="text-2xs text-fg-muted">{s.awb}</Mono></div></td>
                    <td className="whitespace-nowrap px-3 py-2">{s.orderRef}</td>
                    <td className="whitespace-nowrap px-3 py-2">{s.customerName ?? "—"}<div><Mono className="text-2xs text-fg-muted">{s.phoneMasked}</Mono></div></td>
                    <td className="whitespace-nowrap px-3 py-2">{s.city ?? "—"}<div className="text-2xs text-fg-muted">{s.pincode}</div></td>
                    <td className="whitespace-nowrap px-3 py-2">{CARRIERS[s.carrier] ?? s.carrier}</td>
                    <td className="whitespace-nowrap px-3 py-2">{s.paymentMode === "COD" ? <>COD <span className="num text-fg-muted">{money(s.codAmountPaise)}</span></> : <span className="text-fg-muted">{title(s.paymentMode?.toLowerCase())}</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2"><StatusBadge map={SHIPMENT_STATUS} value={s.status} /></td>
                    <td className="num px-3 py-2">{s.attempts}</td>
                    <td className="whitespace-nowrap px-3 py-2">{s.ndrCaseId ? <Link href={`/ndr/${s.ndrCaseId}`} className="inline-flex items-center gap-1.5 hover:underline"><Mono className="text-[11.5px]">{s.ndrCode}</Mono><StatusBadge map={NDR_STATUS} value={s.ndrStatus} /></Link> : <span className="text-fg-subtle">—</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={s.lastEventAt} /></td>
                    <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={s.createdAt} /></td>
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
