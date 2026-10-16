"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { opts, SingleSelect } from "@/components/platform/filters";
import { usePoll } from "@/components/platform/providers";
import { Badge, cx, Empty, ErrorBox, Freshness, Input, LangTag, Mono, PageHeader, Pagination, Panel, SkeletonRows, StatusBadge, Timestamp } from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { useDebounced, useUrlState } from "@/lib/platform/hooks";
import { LANG, MESSAGE_STATUS } from "@/lib/platform/labels";

interface Conv {
  id: string; customerName: string | null; phoneMasked: string | null; language: string | null; status: string; shipmentId: string | null;
  ndrCaseId: string | null; ndrCode: string | null; messageCount: number; lastMessageAt: string | null; lastInboundAt: string | null;
  lastDirection: string | null; lastStatus: string | null; lastPreview: string | null; inSessionWindow: boolean;
}

const DEFAULTS = { q: "", language: "", page: "1" };

export function ConversationsView() {
  const poll = usePoll();
  const { state: f, set } = useUrlState(DEFAULTS);
  const [search, setSearch] = useState(f.q);
  const debounced = useDebounced(search, 350);
  useEffect(() => { if (debounced !== f.q) set({ q: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  const query = { ...f, pageSize: 50 };
  const list = useQuery({ queryKey: ["conversations", query], queryFn: () => api<Page<Conv>>("/conversations", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Conversations" description="WhatsApp threads with customers, most recent first. Calls for the same shipment appear inside each thread."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search by customer name</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Customer name" className="pl-8" />
          </label>
          <SingleSelect label="Language" value={f.language} onChange={(language) => set({ language })} options={opts(LANG)} />
        </div>
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={8} cols={4} /> : total === 0 ? (
          <Empty title="No conversations">Threads start when the agent first messages a customer.</Empty>
        ) : (
          <ul className={cx("divide-y divide-line", list.isPlaceholderData && "opacity-60")}>
            {list.data!.items.map((c) => (
              <li key={c.id}>
                <Link prefetch={false} href={`/conversations/${c.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-zy-paper sm:flex-nowrap">
                  <div className="w-48 shrink-0">
                    <p className="truncate text-[13px] font-medium text-fg-strong">{c.customerName ?? "Unknown customer"}</p>
                    <Mono className="text-2xs text-fg-muted">{c.phoneMasked}</Mono>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12.5px] text-fg">
                      <span className="text-fg-subtle">{c.lastDirection === "inbound" ? "Customer: " : c.lastDirection === "outbound" ? "Agent: " : ""}</span>{c.lastPreview ?? "—"}
                    </p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-2xs text-fg-muted">
                      <LangTag code={c.language} />
                      <span>{c.messageCount} messages</span>
                      {c.ndrCode && <span className="font-mono">{c.ndrCode}</span>}
                      {c.lastDirection === "outbound" && <StatusBadge map={MESSAGE_STATUS} value={c.lastStatus} />}
                      {c.inSessionWindow && <Badge tone="ok" dot={false} hint="The customer wrote within 24 hours, so free-form replies are allowed">24 h window open</Badge>}
                    </div>
                  </div>
                  <span className="shrink-0 text-2xs text-fg-muted"><Timestamp iso={c.lastMessageAt} /></span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {total > 0 && <Pagination page={Number(f.page)} pageSize={50} total={total} onPage={(p) => set({ page: String(p) }, { resetPage: false })} />}
      </Panel>
    </>
  );
}
