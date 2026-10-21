"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, History, Lock, RotateCcw, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useSession } from "@/components/platform/providers";
import { Badge, Button, cx, Dialog, ErrorBox, Field, Input, Notice, PageHeader, Panel, PanelHeader, Skeleton, Textarea, Timestamp } from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { LANG, title } from "@/lib/platform/labels";
import type { JsonSchema, PolicyDoc, PublishResult } from "@/lib/platform/types";

export type FieldMeta = { label: string; help?: string; unit?: string };
export type Section = { title: string; description?: string; fields: string[] };

const ENUM_LABEL: Record<string, string> = {
  ...LANG, whatsapp: "WhatsApp", voice: "Voice", out_for_delivery: "When out for delivery", eta_window: "Ahead of the ETA window", both: "Both",
  reattempt: "Re-attempt", reschedule: "Reschedule", address_change: "Address change", phone_change: "Phone change", rto: "Return to origin",
  cancel: "Cancel", escalate: "Escalate to an operator", close_after_sla: "Close as no response after the SLA",
};
const enumLabel = (v: unknown) => ENUM_LABEL[String(v)] ?? title(String(v));

type Config = Record<string, unknown>;

function show(v: unknown, key: string): string {
  if (v === null || v === undefined) return "—";
  if (key.endsWith("_paise") && typeof v === "number") return `₹${(v / 100).toLocaleString("en-IN")}`;
  if (Array.isArray(v)) return v.length ? v.map(enumLabel).join(", ") : "none";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (typeof v === "string" && /^\d{2}:\d{2}:\d{2}$/.test(v)) return v.slice(0, 5);
  return String(v);
}

export function PolicyEditor({ path, kind, pageTitle, description, meta, sections, readPerm, writePerm }: {
  path: string; kind: string; pageTitle: string; description: string; meta: Record<string, FieldMeta>; sections: Section[]; readPerm: string; writePerm: string;
}) {
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["policy", kind], queryFn: () => api<PolicyDoc>(path), enabled: can(readPerm) });
  const [draft, setDraft] = useState<Config | null>(null);
  const [preview, setPreview] = useState<PublishResult | null>(null);
  const [note, setNote] = useState("");
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  useEffect(() => { if (q.data) setDraft(structuredClone(q.data.config)); }, [q.data]);
  const writable = can(writePerm);

  const dirtyKeys = useMemo(() => (q.data && draft ? Object.keys(draft).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(q.data!.config[k])) : []), [draft, q.data]);
  const dry = useMutation({ mutationFn: () => api<PublishResult>(path, { method: "PATCH", body: { config: draft, changeNote: "dry run", dryRun: true } }), onSuccess: (r) => { setPreview(r); setNote(""); } });
  const publish = useMutation({
    mutationFn: () => api<PublishResult>(path, { method: "PATCH", body: { config: draft, changeNote: note.trim(), dryRun: false } }),
    onSuccess: () => { setPreview(null); qc.invalidateQueries({ queryKey: ["policy", kind] }); },
  });
  const fieldErrors = useMemo(() => {
    const e = (dry.error ?? publish.error) as ApiError | null;
    const out: Record<string, string> = {};
    e?.fields?.forEach((f) => { const k = f.loc.find((x) => x in (draft ?? {})); if (k) out[k] = f.msg; });
    return out;
  }, [dry.error, publish.error, draft]);

  if (!can(readPerm)) return <><PageHeader title={pageTitle} /><Panel><p className="flex items-center gap-2 px-4 py-8 text-[13px] text-fg-muted"><Lock className="h-4 w-4" />Your role cannot view this.</p></Panel></>;
  if (q.isError) return <><PageHeader title={pageTitle} /><Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel></>;
  if (!q.data || !draft) return <><PageHeader title={pageTitle} /><Skeleton className="h-96 w-full" /></>;
  const schema = q.data.schema;

  return (
    <>
      <PageHeader title={pageTitle} description={description}
        meta={<><Badge tone="ok" dot={false}>Version {q.data.version} active</Badge><span>Published <Timestamp iso={q.data.createdAt} /></span>{q.data.changeNote && <span>· “{q.data.changeNote}”</span>}<span>· rules {q.data.rulesVersion}</span></>}
        actions={writable ? <>
          <Button variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} disabled={!dirtyKeys.length} onClick={() => { setDraft(structuredClone(q.data!.config)); dry.reset(); publish.reset(); }}>Discard changes</Button>
          <Button variant="primary" icon={<Eye className="h-3.5 w-3.5" />} disabled={!dirtyKeys.length} loading={dry.isPending} onClick={() => dry.mutate()}>Review {dirtyKeys.length || ""} change{dirtyKeys.length === 1 ? "" : "s"}</Button>
        </> : <Badge tone="muted" dot={false}>Read only for your role</Badge>} />
      {(dry.error || publish.error) && !preview ? <Panel className="mb-4"><ErrorBox error={dry.error ?? publish.error} compact /></Panel> : null}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          {sections.map((s) => (
            <Panel key={s.title}>
              <PanelHeader title={s.title} subtitle={s.description} />
              <div className="divide-y divide-line">
                {s.fields.filter((f) => schema.properties?.[f]).map((f) => (
                  <FieldRow key={f} name={f} schema={schema.properties![f]} meta={meta[f]} value={draft[f]} changed={dirtyKeys.includes(f)} error={fieldErrors[f]}
                    disabled={!writable} onChange={(v) => setDraft({ ...draft, [f]: v })} />
                ))}
              </div>
            </Panel>
          ))}
        </div>
        <Panel className="self-start">
          <PanelHeader title="Version history" subtitle="Every published change, newest first" />
          <ul className="divide-y divide-line">
            {q.data.history.map((h) => (
              <li key={h.version}>
                <button onClick={() => setViewVersion(h.version)} className="w-full px-4 py-2.5 text-left text-[12.5px] hover:bg-zy-paper">
                  <div className="flex items-center gap-2"><History className="h-3.5 w-3.5 text-fg-subtle" aria-hidden /><span className="font-medium text-fg-strong">Version {h.version}</span>{h.active && <Badge tone="ok" dot={false}>Active</Badge>}<span className="ml-auto text-2xs text-fg-muted"><Timestamp iso={h.createdAt} /></span></div>
                  {h.changeNote && <p className="mt-0.5 truncate pl-5 text-2xs text-fg-muted">{h.changeNote}</p>}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      {preview && (
        <Dialog open onClose={() => setPreview(null)} title={`Publish version ${q.data.version + 1}`} width="max-w-2xl"
          footer={<><Button variant="ghost" onClick={() => setPreview(null)}>Keep editing</Button>
            <Button variant="primary" icon={<Upload className="h-3.5 w-3.5" />} loading={publish.isPending} disabled={note.trim().length < 3 || !Object.keys(preview.changes).length} onClick={() => publish.mutate()}>Publish</Button></>}>
          <div className="space-y-3">
            <p className="text-[13px] text-fg">The server validated this configuration. It takes effect from each agent's next step, including cases already in progress. Every decision records the version it used.</p>
            {Object.keys(preview.changes).length ? (
              <table className="w-full text-[12.5px]">
                <thead><tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-fg-muted"><th className="py-1.5">Setting</th><th>Now</th><th>After publishing</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(preview.changes).map(([k, c]) => (
                    <tr key={k} className="align-top"><td className="py-1.5 pr-3 font-medium text-fg-strong">{meta[k]?.label ?? schema.properties?.[k]?.title ?? k}</td>
                      <td className="py-1.5 pr-3 text-danger line-through decoration-danger/40">{show(c.from, k)}</td><td className="py-1.5 text-ok">{show(c.to, k)}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : <Notice>No effective change after validation.</Notice>}
            <Field label="What changed and why (shown in the history and audit log)"><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
            {publish.error ? <ErrorBox error={publish.error} compact /> : null}
          </div>
        </Dialog>
      )}
      {viewVersion !== null && <VersionDialog path={path} kind={kind} version={viewVersion} current={q.data.config} meta={meta} schema={schema} onClose={() => setViewVersion(null)} />}
    </>
  );
}

function VersionDialog({ path, kind, version, current, meta, schema, onClose }: { path: string; kind: string; version: number; current: Config; meta: Record<string, FieldMeta>; schema: JsonSchema; onClose: () => void }) {
  const q = useQuery({ queryKey: ["policy", kind, "v", version], queryFn: () => api<{ version: number; config: Config; changeNote: string | null; createdAt: string }>(`${path}/versions/${version}`) });
  const diff = q.data ? Object.keys({ ...current, ...q.data.config }).filter((k) => JSON.stringify(current[k]) !== JSON.stringify(q.data!.config[k])) : [];
  return (
    <Dialog open onClose={onClose} title={`Version ${version}`} width="max-w-2xl">
      {q.isError ? <ErrorBox error={q.error} compact /> : !q.data ? <Skeleton className="h-32 w-full" /> : (
        <div className="space-y-3 text-[12.5px]">
          <p className="text-fg-muted">Published <Timestamp iso={q.data.createdAt} mode="absolute" />{q.data.changeNote ? ` — “${q.data.changeNote}”` : ""}</p>
          {diff.length ? <>
            <p className="font-medium text-fg-strong">Differs from the active version in {diff.length} setting{diff.length > 1 ? "s" : ""}:</p>
            <ul className="space-y-1">{diff.map((k) => <li key={k}><span className="font-medium">{meta[k]?.label ?? schema.properties?.[k]?.title ?? k}</span>: {show(q.data!.config[k], k)} <span className="text-fg-subtle">(now {show(current[k], k)})</span></li>)}</ul>
          </> : <Notice>Identical to the active version.</Notice>}
        </div>
      )}
    </Dialog>
  );
}

function FieldRow({ name, schema, meta, value, onChange, changed, error, disabled }: {
  name: string; schema: JsonSchema; meta?: FieldMeta; value: unknown; onChange: (v: unknown) => void; changed: boolean; error?: string; disabled: boolean;
}) {
  const label = meta?.label ?? schema.title ?? name;
  const range = schema.minimum !== undefined || schema.maximum !== undefined
    ? `${schema.minimum !== undefined ? `min ${name.endsWith("_paise") ? `₹${schema.minimum / 100}` : schema.minimum}` : ""}${schema.minimum !== undefined && schema.maximum !== undefined ? " · " : ""}${schema.maximum !== undefined ? `max ${schema.maximum}` : ""}` : null;
  return (
    <div className={cx("grid gap-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,320px)] md:items-center", changed && "bg-zy-brand-soft/40")}>
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-[13px] font-medium text-fg-strong">{label}{changed && <Badge tone="brand" dot={false}>Changed</Badge>}</p>
        {meta?.help && <p className="mt-0.5 text-2xs text-fg-muted">{meta.help}</p>}
        {error && <p className="mt-0.5 text-2xs text-danger">{error}</p>}
      </div>
      <div className="min-w-0"><Control name={name} schema={schema} meta={meta} value={value} onChange={onChange} disabled={disabled} />{range && <p className="mt-0.5 text-[10.5px] text-fg-subtle">{range}</p>}</div>
    </div>
  );
}

function Control({ name, schema, meta, value, onChange, disabled }: { name: string; schema: JsonSchema; meta?: FieldMeta; value: unknown; onChange: (v: unknown) => void; disabled: boolean }) {
  if (schema.type === "boolean") {
    const on = Boolean(value);
    return (
      <button type="button" role="switch" aria-checked={on} aria-label={meta?.label ?? name} disabled={disabled} onClick={() => onChange(!on)}
        className={cx("relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50", on ? "bg-zy-brand" : "bg-line-strong")}>
        <span className={cx("inline-block h-4 w-4 rounded-full bg-white shadow transition-transform", on ? "translate-x-[18px]" : "translate-x-0.5")} />
      </button>
    );
  }
  if (schema.type === "array" && schema.items?.enum) {
    const sel = (value as unknown[]) ?? [];
    return (
      <div className="flex flex-wrap gap-1.5">
        {schema.items.enum.map((opt) => {
          const on = sel.includes(opt);
          return (
            <button key={String(opt)} type="button" aria-pressed={on} disabled={disabled} onClick={() => onChange(on ? sel.filter((x) => x !== opt) : [...sel, opt])}
              className={cx("rounded-full border px-2.5 py-0.5 text-2xs font-medium transition-colors disabled:cursor-not-allowed", on ? "border-zy-ink bg-zy-ink text-white" : "border-line-strong text-fg hover:bg-zy-paper")}>
              {enumLabel(opt)}
            </button>
          );
        })}
      </div>
    );
  }
  if (schema.type === "array") {
    return <ListInput value={(value as number[]) ?? []} onChange={onChange} disabled={disabled} unit={meta?.unit} />;
  }
  if (schema.enum) {
    return (
      <select value={String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)} className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 text-[13px] text-fg-strong focus:outline-none">
        {schema.enum.map((o) => <option key={String(o)} value={String(o)}>{enumLabel(o)}</option>)}
      </select>
    );
  }
  if ((schema as JsonSchema & { format?: string }).format === "time") {
    return <Input type="time" value={String(value ?? "").slice(0, 5)} disabled={disabled} onChange={(e) => onChange(`${e.target.value}:00`)} className="w-32" />;
  }
  if (schema.type === "integer" || schema.type === "number") {
    const paise = name.endsWith("_paise");
    const shown = value === null || value === undefined ? "" : paise ? Number(value) / 100 : Number(value);
    return (
      <div className="flex items-center gap-2">
        {paise && <span className="text-[13px] text-fg-muted">₹</span>}
        <Input type="number" inputMode="decimal" value={shown} disabled={disabled} step={schema.type === "number" ? 0.01 : 1}
          onChange={(e) => { if (e.target.value === "") return; const n = Number(e.target.value); onChange(paise ? Math.round(n * 100) : schema.type === "integer" ? Math.round(n) : n); }} className="w-36" />
        {meta?.unit && <span className="text-2xs text-fg-muted">{meta.unit}</span>}
      </div>
    );
  }
  return <Input value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
}

function ListInput({ value, onChange, disabled, unit }: { value: number[]; onChange: (v: unknown) => void; disabled: boolean; unit?: string }) {
  const [text, setText] = useState(value.join(", "));
  useEffect(() => setText(value.join(", ")), [value]);
  return (
    <div className="flex items-center gap-2">
      <Input value={text} disabled={disabled} onChange={(e) => setText(e.target.value)}
        onBlur={() => onChange(text.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => Number.isFinite(n)).map(Math.round))} className="w-48" />
      {unit && <span className="text-2xs text-fg-muted">{unit}</span>}
    </div>
  );
}
