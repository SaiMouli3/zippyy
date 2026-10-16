"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnDef, flexRender, getCoreRowModel, RowSelectionState, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, RotateCcw, Search, SlidersHorizontal, UserRoundCog } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ActiveChips, ColumnMenu, MultiSelect, opts, SingleSelect } from "@/components/platform/filters";
import { usePoll, useSession } from "@/components/platform/providers";
import {
  Badge, Button, ConfirmDialog, cx, Dialog, Empty, ErrorBox, Freshness, Input, LangTag, Mono, PageHeader, Pagination, Panel,
  SkeletonRows, SlaCell, StatusBadge, Tabs, Timestamp, Tooltip,
} from "@/components/platform/ui";
import { api, ApiError, Page, qs } from "@/lib/platform/api";
import { dateOnly, money, num, window_ } from "@/lib/platform/format";
import { useDebounced, useLocalStorage, useUrlState } from "@/lib/platform/hooks";
import {
  ACTION_STATUS, AGENT_STATUS, CALL_RESULT, CALL_STATUS, CARRIERS, CONTACTABILITY, LANG, MESSAGE_STATUS, NDR_REASON, NDR_STATUS,
  RECOVERY, SHIPMENT_STATUS, title,
} from "@/lib/platform/labels";
import type { NdrRow } from "@/lib/platform/types";

const DEFAULTS = {
  queue: "open", q: "", status: "", reason: "", carrier: "", language: "", payment: "", sla: "", agentStatus: "", contactability: "",
  whatsappStatus: "", callOutcome: "", recovery: "", rto: "", minAttempts: "", city: "", state: "", pincode: "", openedFrom: "",
  openedTo: "", sort: "sla", order: "asc", page: "1", pageSize: "50",
};
type F = typeof DEFAULTS;

const QUEUE_TABS = [
  { id: "open", label: "Open" }, { id: "urgent", label: "Urgent" }, { id: "escalated", label: "Escalated" },
  { id: "awaiting_carrier", label: "Awaiting carrier" }, { id: "carrier_unknown", label: "Carrier unknown" },
  { id: "near_deadline", label: "Due in 4 h" }, { id: "callback", label: "Callbacks" }, { id: "call_failures", label: "Call failures" },
  { id: "low_confidence", label: "Unclear intent" }, { id: "restricted", label: "Restricted" }, { id: "recovered", label: "Recovered" },
  { id: "rto", label: "RTO" }, { id: "resolved", label: "Closed" }, { id: "all", label: "All" },
];

const FILTER_LABEL: Record<string, string> = {
  status: "Status", reason: "Reason", carrier: "Carrier", language: "Language", payment: "Payment", sla: "SLA", agentStatus: "Agent",
  contactability: "Contact", whatsappStatus: "WhatsApp", callOutcome: "Call", recovery: "Outcome", rto: "RTO", minAttempts: "Attempts ≥",
  city: "City", state: "State", pincode: "Pincode", openedFrom: "Opened from", openedTo: "Opened before", q: "Search",
};
const SLA_OPTS = [{ value: "breached", label: "Breached" }, { value: "due_4h", label: "Due within 4 h" }, { value: "due_24h", label: "Due within 24 h" }];
const RTO_OPTS = [{ value: "initiated", label: "RTO in progress" }, { value: "completed", label: "Returned to origin" }, { value: "none", label: "No RTO" }];
const PAYMENT_OPTS = [{ value: "COD", label: "Cash on delivery" }, { value: "PREPAID", label: "Prepaid" }];
const CALL_OUTCOME_OPTS = opts({ ...Object.fromEntries(Object.entries(CALL_RESULT).map(([k, v]) => [k, v.label])) });

const SORT_KEYS: Record<string, string> = { code: "code", status: "status", attempts: "attempts", sla: "sla", lastContact: "lastContact", opened: "opened", updated: "updated" };

function pending(p: string | null) {
  if (!p) return <span className="text-fg-subtle">—</span>;
  const [action, status] = p.split(":");
  const e = ACTION_STATUS[status];
  return <Badge tone={e?.tone ?? "neutral"} hint={e?.hint}>{title(action)} · {(e?.label ?? status).toLowerCase()}</Badge>;
}

export function NdrView() {
  const { can } = useSession();
  const poll = usePoll();
  const router = useRouter();
  const qc = useQueryClient();
  const { state: f, set, clear } = useUrlState<F>(DEFAULTS);
  const [search, setSearch] = useState(f.q);
  const debounced = useDebounced(search, 350);
  useEffect(() => { if (debounced !== f.q) set({ q: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSearch(f.q); }, [f.q]);
  const [showFilters, setShowFilters] = useState(false);
  const [hidden, setHidden] = useLocalStorage<string[]>("zpy.ndr.hidden", ["merchant", "pincode", "updated", "contactability", "shipmentStatus"]);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [bulk, setBulk] = useState<null | "retry" | "escalate">(null);

  const query = useMemo(() => {
    const { page, pageSize, queue, ...rest } = f;
    const out: Record<string, string> = { ...rest, page, pageSize };
    if (queue !== "all") out.queue = queue;
    if (rest.openedFrom) out.openedFrom = new Date(rest.openedFrom + "T00:00:00+05:30").toISOString();
    if (rest.openedTo) out.openedTo = new Date(rest.openedTo + "T00:00:00+05:30").toISOString();
    return out;
  }, [f]);

  const list = useQuery({
    queryKey: ["ndr", "list", query], queryFn: ({ signal }) => api<Page<NdrRow>>("/ndr", { query, signal }),
    placeholderData: keepPreviousData, refetchInterval: poll,
  });
  useEffect(() => setSelection({}), [query]);

  const columns = useMemo<ColumnDef<NdrRow>[]>(() => [
    {
      id: "select", enableHiding: false, size: 32,
      header: ({ table }) => <input type="checkbox" aria-label="Select all on this page" className="accent-[#D54029]"
        checked={table.getIsAllPageRowsSelected()} ref={(el) => { if (el) el.indeterminate = table.getIsSomePageRowsSelected(); }}
        onChange={table.getToggleAllPageRowsSelectedHandler()} />,
      cell: ({ row }) => <input type="checkbox" aria-label={`Select ${row.original.code}`} className="accent-[#D54029]"
        checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} onClick={(e) => e.stopPropagation()} />,
    },
    { id: "code", header: "Case", cell: ({ row: { original: r } }) => (
      <div className="flex items-center gap-1.5">
        <Link href={`/ndr/${r.id}`} className="font-mono text-[12px] font-medium text-fg-strong hover:text-zy-brand hover:underline" onClick={(e) => e.stopPropagation()}>{r.code}</Link>
        {r.priority === "urgent" && <Tooltip text="Urgent priority"><span className="rounded bg-danger px-1 text-[10px] font-bold uppercase leading-4 text-white">!</span></Tooltip>}
        {r.hasOpenEscalation && <Tooltip text="Open escalation"><UserRoundCog className="h-3.5 w-3.5 text-danger" aria-label="Open escalation" /></Tooltip>}
      </div>) },
    { id: "order", header: "Order / AWB", cell: ({ row: { original: r } }) => (
      <div className="leading-4"><div className="text-fg-strong">{r.orderRef ?? "—"}</div><Mono className="text-2xs text-fg-muted">{r.awb ?? "—"}</Mono></div>) },
    { id: "merchant", header: "Merchant", cell: ({ row }) => row.original.merchant },
    { id: "customer", header: "Customer", cell: ({ row: { original: r } }) => (
      <div className="leading-4"><div className="max-w-[160px] truncate text-fg-strong">{r.customerName ?? "—"}</div><Mono className="text-2xs text-fg-muted">{r.phoneMasked ?? ""}</Mono></div>) },
    { id: "location", header: "City / state", cell: ({ row: { original: r } }) => (
      <div className="leading-4"><div className="max-w-[140px] truncate">{r.city ?? "—"}</div><div className="text-2xs text-fg-muted">{r.state ?? ""}</div></div>) },
    { id: "pincode", header: "Pincode", cell: ({ row }) => <Mono>{row.original.pincode ?? "—"}</Mono> },
    { id: "carrier", header: "Carrier", cell: ({ row }) => CARRIERS[row.original.carrier] ?? row.original.carrier },
    { id: "payment", header: "Payment", cell: ({ row: { original: r } }) => r.paymentMode === "COD"
      ? <span className="whitespace-nowrap">COD <span className="num text-fg-muted">{money(r.codAmountPaise)}</span></span> : <span className="text-fg-muted">{r.paymentMode ? title(r.paymentMode.toLowerCase()) : "—"}</span> },
    { id: "shipmentStatus", header: "Shipment", cell: ({ row }) => <StatusBadge map={SHIPMENT_STATUS} value={row.original.shipmentStatus} /> },
    { id: "status", header: "NDR status", cell: ({ row }) => <StatusBadge map={NDR_STATUS} value={row.original.status} /> },
    { id: "reason", header: "Reason", cell: ({ row: { original: r } }) => (
      <Tooltip text={r.carrierReason ? `Courier said: “${r.carrierReason}”` : "No courier remark"}><span className="whitespace-nowrap">{NDR_REASON[r.reason] ?? r.reason}</span></Tooltip>) },
    { id: "attempts", header: "Attempts", cell: ({ row }) => <span className={cx("num", row.original.attempts >= 3 && "font-semibold text-danger")}>{row.original.attempts}</span> },
    { id: "language", header: "Language", cell: ({ row: { original: r } }) => <LangTag code={r.languageConfirmed ?? r.languagePredicted} confirmed={!!r.languageConfirmed} /> },
    { id: "preference", header: "Preferred slot", cell: ({ row: { original: r } }) => r.preferredDate
      ? <span className="whitespace-nowrap">{dateOnly(r.preferredDate)}{r.preferredWindow ? <span className="text-fg-muted"> · {window_(r.preferredWindow)}</span> : null}</span> : <span className="text-fg-subtle">—</span> },
    { id: "whatsapp", header: "WhatsApp", cell: ({ row }) => <StatusBadge map={MESSAGE_STATUS} value={row.original.whatsappStatus} /> },
    { id: "call", header: "Call", cell: ({ row: { original: r } }) => <StatusBadge map={r.callOutcome && CALL_RESULT[r.callOutcome] ? CALL_RESULT : CALL_STATUS} value={r.callOutcome} /> },
    { id: "lastContact", header: "Last contact", cell: ({ row: { original: r } }) => r.lastContactAt
      ? <span className="whitespace-nowrap"><Timestamp iso={r.lastContactAt} />{r.lastContactChannel ? <span className="text-fg-muted"> · {title(r.lastContactChannel)}</span> : null}</span> : <span className="text-fg-subtle">None yet</span> },
    { id: "agent", header: "Agent", cell: ({ row }) => <StatusBadge map={AGENT_STATUS} value={row.original.agentStatus} /> },
    { id: "pending", header: "Pending action", cell: ({ row }) => pending(row.original.pendingAction) },
    { id: "sla", header: "SLA", cell: ({ row: { original: r } }) => <SlaCell iso={r.slaDueAt} closed={!["open", "contacting", "awaiting_customer", "decided", "escalated"].includes(r.status)} /> },
    { id: "recovery", header: "Outcome", cell: ({ row }) => <StatusBadge map={RECOVERY} value={row.original.recoveryOutcome} /> },
    { id: "contactability", header: "Contactability", cell: ({ row }) => <StatusBadge map={CONTACTABILITY} value={row.original.contactability} /> },
    { id: "opened", header: "Opened", cell: ({ row }) => <Timestamp iso={row.original.openedAt} /> },
    { id: "updated", header: "Updated", cell: ({ row }) => <Timestamp iso={row.original.updatedAt} /> },
  ], []);

  const table = useReactTable({
    data: list.data?.items ?? [], columns, getCoreRowModel: getCoreRowModel(), getRowId: (r) => r.id,
    state: { rowSelection: selection, columnVisibility: Object.fromEntries(hidden.map((h) => [h, false])) },
    onRowSelectionChange: setSelection, enableRowSelection: can("ndr.act"), manualPagination: true, manualSorting: true,
  });
  const selectedIds = Object.keys(selection).filter((k) => selection[k]);

  const filterKeys = Object.keys(FILTER_LABEL) as (keyof F)[];
  const chips = filterKeys.filter((k) => f[k]).map((k) => ({
    key: k, label: <><span className="text-fg-muted">{FILTER_LABEL[k]}:</span> <span className="font-medium">{chipValue(k, f[k])}</span></>,
    onRemove: () => set({ [k]: "" } as Partial<F>),
  }));

  function sortBy(id: string) {
    const key = SORT_KEYS[id];
    if (!key) return;
    if (f.sort === key) set({ order: f.order === "asc" ? "desc" : "asc" }, { resetPage: false });
    else set({ sort: key, order: key === "sla" ? "asc" : "desc" }, { resetPage: false });
  }

  const exportHref = `/api/v1/ndr/export.csv${qs(Object.fromEntries(Object.entries(query).filter(([k]) => !["page", "pageSize", "sort", "order"].includes(k))))}`;
  const total = list.data?.total ?? 0;

  return (
    <>
      <PageHeader title="NDR command center"
        description="Every failed delivery attempt, what the agent is doing about it, and what still needs a person."
        meta={<Freshness at={list.data?.generatedAt} fetching={list.isFetching} onRefresh={() => list.refetch()} />}
        actions={<>
          {can("export.csv") && (
            <a href={exportHref} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-3 text-[13px] font-medium text-fg-strong hover:bg-zy-paper" download>
              <Download className="h-3.5 w-3.5" aria-hidden /> Export CSV
            </a>
          )}
        </>} />

      <Panel>
        <Tabs className="px-2" tabs={QUEUE_TABS.map((t) => ({ ...t, count: t.id === f.queue && list.data ? total : null }))} value={f.queue} onChange={(queue) => set({ queue })} />
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search cases</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={can("pii.unmask") ? "Case, order, AWB, customer or full phone" : "Case, order, AWB or customer"} className="pl-8" />
          </label>
          <MultiSelect label="Status" value={f.status} onChange={(status) => set({ status })} options={opts(NDR_STATUS)} />
          <MultiSelect label="Reason" value={f.reason} onChange={(reason) => set({ reason })} options={opts(NDR_REASON)} />
          <MultiSelect label="Carrier" value={f.carrier} onChange={(carrier) => set({ carrier })} options={opts(CARRIERS)} />
          <SingleSelect label="SLA" value={f.sla} onChange={(sla) => set({ sla })} options={SLA_OPTS} />
          <Button size="md" variant={showFilters ? "dark" : "secondary"} icon={<SlidersHorizontal className="h-3.5 w-3.5" />} onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
            More filters
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <ColumnMenu hidden={hidden} onChange={setHidden}
              columns={table.getAllLeafColumns().filter((c) => c.id !== "select").map((c) => ({ id: c.id, label: String(c.columnDef.header), required: c.id === "code" }))} />
          </div>
        </div>
        {showFilters && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-zy-paper px-3 py-2.5">
            <MultiSelect label="Language" value={f.language} onChange={(language) => set({ language })} options={opts(LANG)} />
            <MultiSelect label="Agent" value={f.agentStatus} onChange={(agentStatus) => set({ agentStatus })} options={opts(AGENT_STATUS)} />
            <MultiSelect label="WhatsApp" value={f.whatsappStatus} onChange={(whatsappStatus) => set({ whatsappStatus })} options={opts(MESSAGE_STATUS)} />
            <MultiSelect label="Call" value={f.callOutcome} onChange={(callOutcome) => set({ callOutcome })} options={CALL_OUTCOME_OPTS} />
            <MultiSelect label="Contact" value={f.contactability} onChange={(contactability) => set({ contactability })} options={opts(CONTACTABILITY)} />
            <MultiSelect label="Outcome" value={f.recovery} onChange={(recovery) => set({ recovery })} options={opts(RECOVERY)} />
            <SingleSelect label="Payment" value={f.payment} onChange={(payment) => set({ payment })} options={PAYMENT_OPTS} />
            <SingleSelect label="RTO" value={f.rto} onChange={(rto) => set({ rto })} options={RTO_OPTS} />
            <SingleSelect label="Attempts ≥" value={f.minAttempts} onChange={(minAttempts) => set({ minAttempts })} options={["2", "3", "4"].map((v) => ({ value: v, label: v }))} />
            <TextFilter label="City" value={f.city} onCommit={(city) => set({ city })} />
            <TextFilter label="State" value={f.state} onCommit={(state) => set({ state })} />
            <TextFilter label="Pincode" value={f.pincode} onCommit={(pincode) => set({ pincode })} pattern="\d{6}" width="w-24" />
            <label className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2.5 text-[12.5px]">
              <span className="text-fg-muted">Opened</span>
              <input type="date" value={f.openedFrom} onChange={(e) => set({ openedFrom: e.target.value })} className="bg-transparent text-[12.5px] focus:outline-none" aria-label="Opened from" />
              <span className="text-fg-subtle">–</span>
              <input type="date" value={f.openedTo} onChange={(e) => set({ openedTo: e.target.value })} className="bg-transparent text-[12.5px] focus:outline-none" aria-label="Opened before" />
            </label>
          </div>
        )}
        {(chips.length > 0 || selectedIds.length > 0) && (
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
            {selectedIds.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2" role="region" aria-label="Bulk actions">
                <span className="text-[12.5px] font-medium text-fg-strong">{selectedIds.length} selected</span>
                <Button size="sm" icon={<RotateCcw className="h-3 w-3" />} onClick={() => setBulk("retry")}>Retry contact</Button>
                <Button size="sm" icon={<UserRoundCog className="h-3 w-3" />} onClick={() => setBulk("escalate")}>Escalate</Button>
                <Button size="sm" variant="ghost" onClick={() => setSelection({})}>Clear selection</Button>
              </div>
            ) : <ActiveChips chips={chips} onClear={() => { clear(); setSearch(""); }} />}
          </div>
        )}

        {list.isError ? <ErrorBox error={list.error} onRetry={() => list.refetch()} /> : list.isLoading ? <SkeletonRows rows={10} cols={8} /> : total === 0 ? (
          <Empty title={chips.length ? "No cases match these filters" : f.queue === "open" ? "No open NDR cases" : "Nothing in this queue"}
            action={chips.length ? <Button onClick={() => { clear(); setSearch(""); }}>Clear filters</Button> : undefined}>
            {chips.length ? "Try removing a filter or searching by AWB instead." : "New cases appear here as soon as a carrier reports a failed delivery."}
          </Empty>
        ) : (
          <div className={cx("overflow-x-auto scrollbar-thin transition-opacity", list.isPlaceholderData && "opacity-60")}>
            <table className="w-full min-w-[1100px] border-collapse text-[12.5px]">
              <thead className="sticky top-0 z-10 bg-zy-paper">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id} className="border-b border-line">
                    {hg.headers.map((h) => {
                      const key = SORT_KEYS[h.column.id];
                      const active = key && f.sort === key;
                      return (
                        <th key={h.id} scope="col" aria-sort={active ? (f.order === "asc" ? "ascending" : "descending") : undefined}
                          className={cx("whitespace-nowrap px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted", h.column.id === "select" && "w-8 pr-0")}>
                          {key ? (
                            <button onClick={() => sortBy(h.column.id)} className="inline-flex items-center gap-1 uppercase hover:text-fg-strong">
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              {active ? (f.order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-40" />}
                            </button>
                          ) : flexRender(h.column.columnDef.header, h.getContext())}
                        </th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-line">
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} onClick={(e) => { if (!(e.target as HTMLElement).closest("a, button, input")) router.push(`/ndr/${row.original.id}`); }}
                    className={cx("cursor-pointer align-middle hover:bg-zy-paper", row.getIsSelected() && "bg-zy-brand-soft/50")}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className={cx("whitespace-nowrap px-3 py-2", cell.column.id === "select" && "w-8 pr-0")}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > 0 && (
          <div className="flex items-center justify-between border-t border-line">
            <label className="flex items-center gap-1.5 pl-4 text-2xs text-fg-muted">
              Rows
              <select value={f.pageSize} onChange={(e) => set({ pageSize: e.target.value })} className="rounded border border-line bg-surface px-1 py-0.5 text-2xs">
                {["25", "50", "100", "200"].map((n) => <option key={n}>{n}</option>)}
              </select>
            </label>
            <div className="flex-1"><Pagination page={Number(f.page)} pageSize={Number(f.pageSize)} total={total} onPage={(p) => set({ page: String(p) }, { resetPage: false })} /></div>
          </div>
        )}
      </Panel>

      <BulkDialog action={bulk} ids={selectedIds} codes={Object.fromEntries((list.data?.items ?? []).map((r) => [r.id, r.code]))}
        onClose={() => setBulk(null)} onDone={() => { setSelection({}); qc.invalidateQueries({ queryKey: ["ndr"] }); }} />
    </>
  );
}

function chipValue(k: string, v: string): string {
  const maps: Record<string, Record<string, string | { label: string }>> = {
    status: NDR_STATUS, reason: NDR_REASON, carrier: CARRIERS, language: LANG, agentStatus: AGENT_STATUS, contactability: CONTACTABILITY,
    whatsappStatus: MESSAGE_STATUS, callOutcome: CALL_RESULT, recovery: RECOVERY,
  };
  if (k === "sla") return SLA_OPTS.find((o) => o.value === v)?.label ?? v;
  if (k === "rto") return RTO_OPTS.find((o) => o.value === v)?.label ?? v;
  const m = maps[k];
  if (!m) return v;
  return v.split(",").map((x) => { const e = m[x]; return typeof e === "string" ? e : e?.label ?? x; }).join(", ");
}

function TextFilter({ label, value, onCommit, pattern, width = "w-32" }: { label: string; value: string; onCommit: (v: string) => void; pattern?: string; width?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onCommit(v.trim()); }} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface pl-2.5 text-[12.5px]">
      <label className="text-fg-muted" htmlFor={`tf-${label}`}>{label}</label>
      <input id={`tf-${label}`} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v.trim() !== value && onCommit(v.trim())} pattern={pattern}
        className={cx("h-full bg-transparent pr-2 text-[12.5px] font-medium text-fg-strong focus:outline-none", width)} />
    </form>
  );
}

interface BulkResult { results: { id: string; ok: boolean; code?: string; message?: string }[]; succeeded: number; failed: number }

function BulkDialog({ action, ids, codes, onClose, onDone }: {
  action: null | "retry" | "escalate"; ids: string[]; codes: Record<string, string>; onClose: () => void; onDone: () => void;
}) {
  const [result, setResult] = useState<BulkResult | null>(null);
  const m = useMutation({
    mutationFn: (reason: string) => api<BulkResult>("/ndr/bulk", { method: "POST", body: { ids, action, reason } }),
    onSuccess: (r) => { setResult(r); onDone(); },
  });
  useEffect(() => { if (action) { setResult(null); m.reset(); } }, [action]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!action) return null;
  if (result) {
    return (
      <Dialog open onClose={onClose} title={action === "retry" ? "Retry results" : "Escalation results"}
        footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
        <p className="mb-3 text-[13px]"><span className="font-semibold text-ok">{num(result.succeeded)} succeeded</span>{result.failed > 0 && <>, <span className="font-semibold text-danger">{num(result.failed)} failed</span></>}.
          {action === "retry" && " Retries queue the agent's next contact step; contact limits and opt-outs still apply."}</p>
        <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded-md border border-line">
          {result.results.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2 text-[12.5px]">
              <Mono>{codes[r.id] ?? r.id}</Mono>
              {r.ok ? <Badge tone="ok">{action === "retry" ? "Queued" : "Escalated"}</Badge> : <span className="text-right text-danger">{r.message ?? r.code}</span>}
            </li>
          ))}
        </ul>
      </Dialog>
    );
  }
  return (
    <ConfirmDialog open onClose={onClose} busy={m.isPending} error={m.error as ApiError | null}
      title={action === "retry" ? `Retry contact for ${ids.length} case${ids.length > 1 ? "s" : ""}` : `Escalate ${ids.length} case${ids.length > 1 ? "s" : ""}`}
      confirmLabel={action === "retry" ? "Queue retries" : "Escalate"} onConfirm={(reason) => m.mutate(reason)}
      description={action === "retry"
        ? "The agent restarts its contact step for each case. Each case is checked on its own: closed cases, opted-out customers and cases over their contact limit are skipped and reported."
        : "Each case gets a medium-priority escalation in the operator inbox. Automated contact continues unless the escalation needs approval."}
      ackText="I understand this is recorded against my name in the audit log." />
  );
}
