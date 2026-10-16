"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Steps } from "@/components/platform/case-parts";
import { opts, SingleSelect } from "@/components/platform/filters";
import { usePoll, useSession } from "@/components/platform/providers";
import {
  Badge, Button, cx, Empty, ErrorBox, Freshness, Mono, PageHeader, Pagination, Panel, Skeleton, SkeletonRows, StatusBadge, Tabs, Timestamp,
} from "@/components/platform/ui";
import { api, Page } from "@/lib/platform/api";
import { useUrlState } from "@/lib/platform/hooks";
import { LANG, STEP_STATUS, title } from "@/lib/platform/labels";
import type { Run, Step } from "@/lib/platform/types";

const DEFAULTS = { tab: "runs", agent: "", status: "", failed: "", human: "", language: "", page: "1" };
const AGENTS = { ndr_recovery_agent: "NDR recovery", delivery_readiness_agent: "Pre-delivery confirmation" };
const RUN_STATUS = { running: "Running", completed: "Completed", failed: "Failed" };

type FailedStep = Step & { runId: string; agent: string; trigger: string; ndrCaseId: string | null; ndrCode: string | null; retryable: boolean };

export function AgentActivityView() {
  const { state: f, set } = useUrlState(DEFAULTS);
  return (
    <>
      <PageHeader title="Agent activity"
        description="Every agent run: what triggered it, which tools it called, what the policy engine allowed, and where it failed. Inputs and outputs are stored sanitized." />
      <Panel>
        <Tabs className="px-2" value={f.tab} onChange={(tab) => set({ tab })} tabs={[{ id: "runs", label: "Runs" }, { id: "failed", label: "Failed steps" }]} />
        {f.tab === "failed" ? <FailedSteps page={Number(f.page)} onPage={(p) => set({ page: String(p) }, { resetPage: false })} /> : <Runs f={f} set={set} />}
      </Panel>
    </>
  );
}

function Runs({ f, set }: { f: typeof DEFAULTS; set: (p: Partial<typeof DEFAULTS>, o?: { resetPage?: boolean }) => void }) {
  const poll = usePoll();
  const [open, setOpen] = useState<string | null>(null);
  const query = { agent: f.agent, status: f.status, failed: f.failed || undefined, human: f.human || undefined, language: f.language, page: f.page, pageSize: 50 };
  const list = useQuery({ queryKey: ["agent-runs", query], queryFn: () => api<Page<Run>>("/agent-runs", { query }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
        <SingleSelect label="Agent" value={f.agent} onChange={(agent) => set({ agent })} options={opts(AGENTS)} />
        <SingleSelect label="Status" value={f.status} onChange={(status) => set({ status })} options={opts(RUN_STATUS)} />
        <SingleSelect label="Language" value={f.language} onChange={(language) => set({ language })} options={opts(LANG)} />
        <SingleSelect label="Operator" value={f.human} onChange={(human) => set({ human })} options={[{ value: "true", label: "Involved" }, { value: "false", label: "Not involved" }]} />
        <label className={cx("inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-[12.5px]", f.failed ? "border-fg-subtle bg-zy-paper-2" : "border-line-strong")}>
          <input type="checkbox" checked={f.failed === "true"} onChange={(e) => set({ failed: e.target.checked ? "true" : "" })} className="accent-[#D54029]" /> With failed steps
        </label>
        <span className="ml-auto"><Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} /></span>
      </div>
      {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={10} /> : total === 0 ? (
        <Empty title="No runs match">Runs are recorded every time an agent wakes up: on a carrier event, a customer reply, a timer or an operator retry.</Empty>
      ) : (
        <ul className={cx("divide-y divide-line", list.isPlaceholderData && "opacity-60")}>
          {list.data!.items.map((r) => (
            <li key={r.id}>
              <button onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left text-[12.5px] hover:bg-zy-paper">
                {open === r.id ? <ChevronDown className="h-3.5 w-3.5 text-fg-muted" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5 text-fg-muted" aria-hidden />}
                <span className="w-40 font-medium text-fg-strong">{AGENTS[r.agent as keyof typeof AGENTS] ?? title(r.agent)}</span>
                <span className="w-44 truncate font-mono text-2xs text-fg-muted">{r.trigger}</span>
                <StatusBadge map={STEP_STATUS} value={r.status} />
                {r.hasFailures && <Badge tone="danger">Failed step</Badge>}
                {r.humanInvolved && <Badge tone="info" dot={false}>Operator</Badge>}
                {r.ndrCode && <Link prefetch={false} href={`/ndr/${r.ndrCaseId}`} onClick={(e) => e.stopPropagation()} className="font-mono text-[12px] text-fg hover:underline">{r.ndrCode}</Link>}
                <span className="ml-auto text-2xs text-fg-muted">{r.stepCount} steps · {r.durationMs !== null ? `${r.durationMs} ms` : "running"} · <Timestamp iso={r.startedAt} /></span>
              </button>
              {open === r.id && <RunDetail id={r.id} />}
            </li>
          ))}
        </ul>
      )}
      {total > 0 && <Pagination page={Number(f.page)} pageSize={50} total={total} onPage={(p) => set({ page: String(p) }, { resetPage: false })} />}
    </>
  );
}

function RunDetail({ id }: { id: string }) {
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["agent-runs", "detail", id], queryFn: () => api<Run>(`/agent-runs/${id}`) });
  const retry = useMutation({ mutationFn: () => api(`/agent-runs/${id}/retry`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-runs"] }) });
  return (
    <div className="border-t border-line bg-zy-paper px-4 py-3">
      {q.isError ? <ErrorBox error={q.error} compact /> : !q.data ? <Skeleton className="h-24 w-full" /> : <>
        <div className="mb-2 flex flex-wrap items-center gap-3 text-2xs text-fg-muted">
          <span>Run <Mono className="text-2xs">{q.data.id}</Mono></span>
          {q.data.correlationId && <span>Correlation <Mono className="text-2xs">{q.data.correlationId}</Mono></span>}
          {q.data.nextAction && <span>Next: <span className="font-medium text-fg">{q.data.nextAction}</span></span>}
          {can("agent_runs.retry") && q.data.hasFailures && (
            <span className="ml-auto flex items-center gap-2">
              {retry.isSuccess ? <span className="text-ok">Retry queued</span> : retry.error ? <span className="text-danger">{(retry.error as Error).message}</span> : null}
              <Button size="sm" icon={<RotateCcw className="h-3 w-3" />} loading={retry.isPending} disabled={retry.isSuccess} onClick={() => retry.mutate()}>Retry run</Button>
            </span>
          )}
        </div>
        {q.data.error && <p className="mb-2 text-2xs text-danger">{q.data.error}</p>}
        <Steps steps={q.data.steps ?? []} />
      </>}
    </div>
  );
}

function FailedSteps({ page, onPage }: { page: number; onPage: (p: number) => void }) {
  const poll = usePoll();
  const list = useQuery({ queryKey: ["agent-runs", "failed", page], queryFn: () => api<Page<FailedStep>>("/agent-runs/failed-steps", { query: { page, pageSize: 50 } }), placeholderData: keepPreviousData, refetchInterval: poll });
  const total = list.data?.total ?? 0;
  if (list.isError) return <ErrorBox error={list.error} onRetry={() => list.refetch()} />;
  if (list.isLoading) return <SkeletonRows rows={8} />;
  if (!total) return <Empty title="No failed steps">Every tool call the agents made succeeded or was handled.</Empty>;
  return (
    <>
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full min-w-[900px] text-[12.5px]">
          <thead className="bg-zy-paper">
            <tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">
              {["When", "Tool", "Status", "Error", "Agent / trigger", "Case", "Retries"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2">{h}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {list.data!.items.map((s) => (
              <tr key={s.id} className="align-top">
                <td className="whitespace-nowrap px-3 py-2 text-fg-muted"><Timestamp iso={s.startedAt} /></td>
                <td className="whitespace-nowrap px-3 py-2"><Mono>{s.tool ?? s.kind}</Mono>{s.provider && <div className="text-2xs text-fg-muted">{s.provider}</div>}</td>
                <td className="px-3 py-2"><StatusBadge map={STEP_STATUS} value={s.status} /></td>
                <td className="max-w-[360px] px-3 py-2 text-danger">{s.error ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-2">{AGENTS[s.agent as keyof typeof AGENTS] ?? title(s.agent)}<div className="font-mono text-2xs text-fg-muted">{s.trigger}</div></td>
                <td className="whitespace-nowrap px-3 py-2">{s.ndrCaseId ? <Link prefetch={false} href={`/ndr/${s.ndrCaseId}`} className="font-mono text-[12px] hover:underline">{s.ndrCode}</Link> : "—"}</td>
                <td className="num px-3 py-2">{s.retryCount}{s.retryable ? "" : <span className="ml-1 text-2xs text-fg-subtle">(workflow finished)</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={50} total={total} onPage={onPage} />
    </>
  );
}
