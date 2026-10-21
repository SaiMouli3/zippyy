"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ThreadView } from "@/components/platform/case-parts";
import { usePoll } from "@/components/platform/providers";
import { Badge, ErrorBox, Freshness, LangTag, Mono, Notice, Panel, PanelHeader, Skeleton, Timestamp } from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { useNow } from "@/lib/platform/hooks";
import { LANG } from "@/lib/platform/labels";
import type { Thread } from "@/lib/platform/types";

interface Conversation extends Thread { id: string; shipmentId: string | null; ndrCaseId: string | null; language: string | null; status: string; lastInboundAt: string | null }

export function ConversationView() {
  const { id } = useParams<{ id: string }>();
  const poll = usePoll();
  const now = useNow();
  const q = useQuery({ queryKey: ["conversations", id], queryFn: () => api<Conversation>(`/conversations/${id}`), refetchInterval: poll });
  const back = <Link href="/conversations" className="inline-flex items-center gap-1 text-[12.5px] text-fg-muted hover:text-fg-strong"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Conversations</Link>;
  if (q.isError) return <div className="space-y-3">{back}<Panel>{(q.error as ApiError).status === 404 ? <p className="px-6 py-14 text-center text-[13px] text-fg-muted">Conversation not found in this workspace.</p> : <ErrorBox error={q.error} onRetry={() => q.refetch()} />}</Panel></div>;
  if (!q.data) return <div className="space-y-4">{back}<Skeleton className="h-8 w-64" /><Skeleton className="h-96 w-full" /></div>;
  const c = q.data;
  const windowEnds = c.lastInboundAt ? new Date(c.lastInboundAt).getTime() + 24 * 3600_000 : null;
  const inWindow = windowEnds !== null && windowEnds > now;
  return (
    <div className="space-y-4">
      {back}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="min-w-0">
          <PanelHeader title={c.customer?.name ?? "Conversation"} subtitle="WhatsApp messages and voice calls for this shipment, in order" actions={<Freshness at={c.generatedAt} fetching={q.isFetching} />} />
          <div className="bg-[#F7F5F2] px-4 py-4"><ThreadView thread={c} /></div>
        </Panel>
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Customer" />
            <div className="space-y-2 px-4 py-3 text-[12.5px]">
              <p className="font-medium text-fg-strong">{c.customer?.name ?? "—"}</p>
              <Mono className="text-fg-muted">{c.customer?.phoneMasked ?? "—"}</Mono>
              <p className="flex items-center gap-2"><span className="text-fg-subtle">Language</span>
                <LangTag code={c.customer?.preferredLanguage ?? c.customer?.predictedLanguage ?? c.language} confirmed={!!c.customer?.preferredLanguage} />
                <span className="text-fg-muted">{c.customer?.preferredLanguage ? `${LANG[c.customer.preferredLanguage]} (confirmed)` : "predicted"}</span></p>
              {c.customer?.optedOut && <Badge tone="danger">Opted out of WhatsApp</Badge>}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="WhatsApp service window" />
            <div className="px-4 py-3 text-[12.5px]">
              {inWindow ? (
                <p className="flex items-start gap-2 text-ok"><Clock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><span>Open until <Timestamp iso={new Date(windowEnds!).toISOString()} mode="absolute" />. The agent may reply in free text.</span></p>
              ) : (
                <Notice>{c.lastInboundAt ? "Closed: the customer last wrote more than 24 hours ago." : "The customer has not written yet."} Only approved message templates can be sent until they reply.</Notice>
              )}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Linked records" />
            <div className="space-y-1.5 px-4 py-3 text-[12.5px]">
              {c.ndrCaseId && <Link href={`/ndr/${c.ndrCaseId}`} className="block text-zy-brand hover:underline">Open NDR case</Link>}
              {c.shipmentId && <Link href={`/shipments/${c.shipmentId}`} className="block text-zy-brand hover:underline">Open shipment</Link>}
              {!c.ndrCaseId && !c.shipmentId && <p className="text-fg-muted">None</p>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
