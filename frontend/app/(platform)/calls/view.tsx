"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Languages } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { MultiSelect, opts, SingleSelect } from "@/components/platform/filters";
import { usePoll } from "@/components/platform/providers";
import { cx, Empty, ErrorBox, Freshness, LangTag, Mono, PageHeader, Pagination, Panel, SkeletonRows, StatusBadge, Timestamp } from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { duration } from "@/lib/platform/format";
import { useUrlState } from "@/lib/platform/hooks";
import { CALL_RESULT, CALL_STATUS, LANG, title } from "@/lib/platform/labels";
import type { CallItem } from "@/lib/platform/types";

const DEFAULTS = { status: "", result: "", language: "", switched: "", purpose: "", page: "1" };

export function CallsView() {
  const poll = usePoll();
  const router = useRouter();
  const { state: f, set } = useUrlState(DEFAULTS);
  const query = { ...f, switched: f.switched === "true" ? "true" : undefined, pageSize: 50 };
  const list = useQuery({ queryKey: ["calls", query], queryFn: () => api<Page<CallItem>>("/voice-calls", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Voice calls" description="Outbound calls placed by the Sarvam voice agent. Language switches, outcomes and transcripts are recorded per call."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <MultiSelect label="Status" value={f.status} onChange={(status) => set({ status })} options={opts(CALL_STATUS)} />
          <SingleSelect label="Result" value={f.result} onChange={(result) => set({ result })} options={opts(CALL_RESULT)} />
          <SingleSelect label="Final language" value={f.language} onChange={(language) => set({ language })} options={opts(LANG)} />
          <SingleSelect label="Purpose" value={f.purpose} onChange={(purpose) => set({ purpose })} options={[{ value: "ndr_recovery", label: "NDR recovery" }, { value: "pre_delivery", label: "Pre-delivery" }]} />
          <label className={cx("inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-[12.5px]", f.switched ? "border-fg-subtle bg-zy-paper-2" : "border-line-strong")}>
            <input type="checkbox" checked={f.switched === "true"} onChange={(e) => set({ switched: e.target.checked ? "true" : "" })} className="accent-[#D54029]" />
            Switched language
          </label>
        </div>
        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={8} /> : total === 0 ? (
          <Empty title="No calls match">Calls appear when the agent decides a voice call is the next permitted step.</Empty>
        ) : (
          <div className={cx("overflow-x-auto scrollbar-thin", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[980px] text-[12.5px]">
              <thead className="bg-zy-paper">
                <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                  {["Call", "Customer", "Purpose", "Status", "Result", "Language", "Duration", "Case", "When"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data!.items.map((c) => (
                  <tr key={c.id} className="cursor-pointer hover:bg-zy-paper" onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) router.push(`/calls/${c.id}`); }}>
                    <td className="whitespace-nowrap px-3 py-2"><Link href={`/calls/${c.id}`} className="font-mono text-[12px] font-medium text-fg-strong hover:underline">{c.code}</Link><div className="text-2xs text-fg-muted">attempt {c.attemptNo}</div></td>
                    <td className="whitespace-nowrap px-3 py-2">{c.customerName ?? "—"}<div><Mono className="text-2xs text-fg-muted">{c.phoneMasked}</Mono></div></td>
                    <td className="whitespace-nowrap px-3 py-2">{title(c.purpose)}</td>
                    <td className="whitespace-nowrap px-3 py-2"><StatusBadge map={CALL_STATUS} value={c.status} /></td>
                    <td className="whitespace-nowrap px-3 py-2"><StatusBadge map={CALL_RESULT} value={c.result} /></td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <span className="inline-flex items-center gap-1"><LangTag code={c.startLanguage} />{c.finalLanguage && c.finalLanguage !== c.startLanguage && <>→<LangTag code={c.finalLanguage} confirmed /></>}
                        {c.languageSwitchCount > 0 && <Languages className="h-3.5 w-3.5 text-zy-brand" aria-label={`${c.languageSwitchCount} language switches`} />}</span>
                    </td>
                    <td className="num whitespace-nowrap px-3 py-2">{duration(c.durationSeconds)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{c.ndrCaseId ? <Link href={`/ndr/${c.ndrCaseId}`} className="font-mono text-[12px] hover:underline">{c.ndrCode}</Link> : <span className="text-fg-subtle">—</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={c.startedAt ?? c.at} /></td>
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
