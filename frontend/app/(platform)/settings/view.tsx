"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { useSession } from "@/components/platform/providers";
import {
  Badge, Button, ConfirmDialog, Dialog, Empty, ErrorBox, Field, Input, KeyValue, Mono, Notice, PageHeader, Panel, PanelHeader, Select, Skeleton, Tabs, Timestamp,
} from "@/components/platform/ui";
import { api } from "@/lib/platform/api";
import { useUrlState } from "@/lib/platform/hooks";
import { title } from "@/lib/platform/labels";

interface Settings {
  merchant: { id: string; code: string; brandName: string; legalName: string | null; plan: string | null; isDemo: boolean };
  timezone: string; messageRetentionDays: number; transcriptRetentionDays: number; callRecordingEnabled: boolean; unmaskRequiresReason: boolean;
  opsAlertEmail: string | null; updatedAt: string | null;
}
interface UserRow { id: string; name: string; email: string | null; role: string; active: boolean; lastLoginAt: string | null }
interface Key { id: string; name: string; prefix: string; scopes: string[]; createdAt: string; lastUsedAt: string | null; expiresAt: string | null; revokedAt: string | null }

const SCOPE_HELP: Record<string, string> = {
  "shipments.import": "Create shipments from your order system", "shipments.read": "Read shipments and tracking", "ndr.read": "Read NDR cases",
  "events.ingest": "Send tracking events",
};

export function SettingsView() {
  const { can } = useSession();
  const { state, set } = useUrlState({ tab: "workspace" });
  const tabs = [{ id: "workspace", label: "Workspace" }, { id: "team", label: "Team" }, ...(can("api_keys.manage") ? [{ id: "keys", label: "API keys" }] : [])];
  return (
    <>
      <PageHeader title="Settings" description="Workspace details, data retention, privacy controls, team and API access." />
      <Tabs className="mb-4" value={state.tab} onChange={(tab) => set({ tab })} tabs={tabs} />
      {state.tab === "team" ? <Team /> : state.tab === "keys" && can("api_keys.manage") ? <Keys /> : <Workspace />}
    </>
  );
}

function Workspace() {
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/merchant/settings") });
  const [form, setForm] = useState<Settings | null>(null);
  useEffect(() => { if (q.data) setForm(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<Settings>("/merchant/settings", { method: "PATCH", body: {
      timezone: form!.timezone, messageRetentionDays: form!.messageRetentionDays, transcriptRetentionDays: form!.transcriptRetentionDays,
      callRecordingEnabled: form!.callRecordingEnabled, unmaskRequiresReason: form!.unmaskRequiresReason, opsAlertEmail: form!.opsAlertEmail || null,
    } }),
    onSuccess: (d) => { qc.setQueryData(["settings"], d); },
  });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!form) return <Skeleton className="h-80 w-full" />;
  const editable = can("settings.write");
  const dirty = JSON.stringify(form) !== JSON.stringify(q.data);
  const upd = (p: Partial<Settings>) => { setForm({ ...form, ...p }); save.reset(); };
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Panel>
        <PanelHeader title="Data & privacy" subtitle="Changes are recorded in the audit log" />
        <div className="grid gap-4 px-4 py-4 sm:grid-cols-2">
          <Field label="Timezone" hint="Used for quiet hours, call windows and daily limits."><Input value={form.timezone} disabled={!editable} onChange={(e) => upd({ timezone: e.target.value })} /></Field>
          <Field label="Operations alert email"><Input type="email" value={form.opsAlertEmail ?? ""} disabled={!editable} onChange={(e) => upd({ opsAlertEmail: e.target.value })} /></Field>
          <Field label="Keep message text for" hint="30–3650 days. Older message bodies are hidden."><Input type="number" min={30} max={3650} value={form.messageRetentionDays} disabled={!editable} onChange={(e) => upd({ messageRetentionDays: Number(e.target.value) })} /></Field>
          <Field label="Keep call transcripts for" hint="7–3650 days."><Input type="number" min={7} max={3650} value={form.transcriptRetentionDays} disabled={!editable} onChange={(e) => upd({ transcriptRetentionDays: Number(e.target.value) })} /></Field>
          <label className="flex items-start gap-2 text-[12.5px] sm:col-span-2"><input type="checkbox" className="mt-0.5 accent-[#D54029]" checked={form.callRecordingEnabled} disabled={!editable} onChange={(e) => upd({ callRecordingEnabled: e.target.checked })} />
            <span><span className="font-medium text-fg-strong">Keep call recordings</span><span className="block text-2xs text-fg-muted">Stores the recording when the voice provider returns one. Turn off if your customer notice does not cover recording.</span></span></label>
          <label className="flex items-start gap-2 text-[12.5px] sm:col-span-2"><input type="checkbox" className="mt-0.5 accent-[#D54029]" checked={form.unmaskRequiresReason} disabled={!editable} onChange={(e) => upd({ unmaskRequiresReason: e.target.checked })} />
            <span><span className="font-medium text-fg-strong">Require a reason to reveal contact details</span><span className="block text-2xs text-fg-muted">The reason is stored with the audit entry.</span></span></label>
        </div>
        {editable && (
          <div className="flex items-center justify-end gap-3 border-t border-line px-4 py-3">
            {save.isSuccess && !dirty && <span className="flex items-center gap-1 text-2xs text-ok"><Check className="h-3 w-3" />Saved</span>}
            {save.error ? <span className="text-2xs text-danger">{(save.error as Error).message}</span> : null}
            <Button variant="ghost" disabled={!dirty} onClick={() => setForm(q.data!)}>Discard</Button>
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
          </div>
        )}
      </Panel>
      <Panel className="self-start">
        <PanelHeader title="Workspace" />
        <div className="px-4 py-3">
          <KeyValue cols={1} items={[
            { k: "Brand", v: form.merchant.brandName }, { k: "Legal name", v: form.merchant.legalName ?? "—" }, { k: "Workspace code", v: <Mono>{form.merchant.code}</Mono> },
            { k: "Plan", v: form.merchant.plan ? title(form.merchant.plan) : "—" }, { k: "Data", v: form.merchant.isDemo ? <Badge tone="warn">Demo — simulated providers only</Badge> : <Badge tone="ok">Live</Badge> },
            { k: "Last changed", v: <Timestamp iso={form.updatedAt} /> },
          ]} />
        </div>
      </Panel>
    </div>
  );
}

function Team() {
  const q = useQuery({ queryKey: ["users"], queryFn: () => api<{ items: UserRow[] }>("/merchant/users") });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!q.data) return <Skeleton className="h-60 w-full" />;
  return (
    <Panel>
      <PanelHeader title="Team" subtitle="People with access to this workspace and their role" />
      <table className="w-full text-[12.5px]">
        <thead className="bg-zy-paper"><tr className="border-b border-line text-left text-2xs font-semibold uppercase tracking-wide text-fg-muted">{["Name", "Email", "Role", "Status", "Last sign-in"].map((h) => <th key={h} scope="col" className="px-4 py-2">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">
          {q.data.items.map((u) => (
            <tr key={u.id}>
              <td className="px-4 py-2.5 font-medium text-fg-strong">{u.name}</td>
              <td className="px-4 py-2.5 text-fg-muted">{u.email ?? <span className="text-fg-subtle">Hidden for your role</span>}</td>
              <td className="px-4 py-2.5"><Badge tone="neutral" dot={false}>{title(u.role)}</Badge></td>
              <td className="px-4 py-2.5">{u.active ? <Badge tone="ok">Active</Badge> : <Badge tone="muted">Deactivated</Badge>}</td>
              <td className="px-4 py-2.5 text-fg-muted"><Timestamp iso={u.lastLoginAt} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Keys() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["api-keys"], queryFn: () => api<{ items: Key[]; availableScopes: string[] }>("/merchant/api-keys") });
  const [creating, setCreating] = useState(false);
  const [revoke, setRevoke] = useState<Key | null>(null);
  const revokeM = useMutation({ mutationFn: (id: string) => api(`/merchant/api-keys/${id}/revoke`, { method: "POST" }), onSuccess: () => { setRevoke(null); qc.invalidateQueries({ queryKey: ["api-keys"] }); } });
  if (q.isError) return <Panel><ErrorBox error={q.error} onRetry={() => q.refetch()} /></Panel>;
  if (!q.data) return <Skeleton className="h-60 w-full" />;
  return (
    <Panel>
      <PanelHeader title="API keys" subtitle="For your order system to import shipments and read cases. Keys are stored hashed and shown only once." actions={<Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>New key</Button>} />
      {!q.data.items.length ? <Empty title="No API keys">Create one for each system that integrates with Zippyy.</Empty> : (
        <ul className="divide-y divide-line">
          {q.data.items.map((k) => {
            const expired = k.expiresAt && new Date(k.expiresAt).getTime() < Date.now();
            return (
              <li key={k.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-[12.5px]">
                <KeyRound className="h-4 w-4 text-fg-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-fg-strong">{k.name} <Mono className="ml-1 text-2xs text-fg-muted">{k.prefix}…</Mono></p>
                  <p className="text-2xs text-fg-muted">{k.scopes.join(", ")} · created <Timestamp iso={k.createdAt} /> · last used {k.lastUsedAt ? <Timestamp iso={k.lastUsedAt} /> : "never"}{k.expiresAt ? <> · expires <Timestamp iso={k.expiresAt} /></> : null}</p>
                </div>
                {k.revokedAt ? <Badge tone="muted">Revoked</Badge> : expired ? <Badge tone="warn">Expired</Badge> : <><Badge tone="ok">Active</Badge><Button size="sm" variant="ghost" onClick={() => setRevoke(k)}>Revoke</Button></>}
              </li>
            );
          })}
        </ul>
      )}
      <CreateKey open={creating} onClose={() => { setCreating(false); qc.invalidateQueries({ queryKey: ["api-keys"] }); }} scopes={q.data.availableScopes} />
      <ConfirmDialog open={!!revoke} onClose={() => setRevoke(null)} title={`Revoke ${revoke?.name ?? "key"}`} confirmLabel="Revoke key" tone="danger" requireReason={false}
        busy={revokeM.isPending} error={revokeM.error} onConfirm={() => revoke && revokeM.mutate(revoke.id)} ackText="I understand any system using this key stops working immediately."
        description="Requests with this key are rejected from now on. This cannot be undone; create a new key instead." />
    </Panel>
  );
}

function CreateKey({ open, onClose, scopes }: { open: boolean; onClose: () => void; scopes: string[] }) {
  const [name, setName] = useState("");
  const [sel, setSel] = useState<string[]>(["shipments.import"]);
  const [days, setDays] = useState("365");
  const [copied, setCopied] = useState(false);
  const m = useMutation({ mutationFn: () => api<{ key: string; prefix: string; note: string }>("/merchant/api-keys", { method: "POST", body: { name: name.trim(), scopes: sel, expiresInDays: Number(days) } }) });
  useEffect(() => { if (open) { setName(""); setSel(["shipments.import"]); setDays("365"); setCopied(false); m.reset(); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) return null;
  if (m.data) {
    return (
      <Dialog open onClose={onClose} title="Copy your new key" footer={<Button variant="primary" onClick={onClose}>I&apos;ve stored it</Button>}>
        <div className="space-y-3">
          <Notice tone="warn">This is the only time the full key is shown. Store it in your secret manager; Zippyy keeps only a hash.</Notice>
          <div className="flex items-center gap-2 rounded-md border border-line bg-zy-paper p-2">
            <code className="min-w-0 flex-1 break-all font-mono text-[12px] text-fg-strong">{m.data.key}</code>
            <Button size="sm" icon={copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} onClick={() => navigator.clipboard.writeText(m.data!.key).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</Button>
          </div>
          <p className="text-2xs text-fg-muted">Send it as the <Mono className="text-2xs">Authorization: Bearer</Mono> header.</p>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog open onClose={onClose} title="New API key"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={name.trim().length < 3 || !sel.length} onClick={() => m.mutate()}>Create key</Button></>}>
      <div className="space-y-3">
        <Field label="Name" hint="Which system uses it, e.g. “Order management”."><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} /></Field>
        <fieldset>
          <legend className="text-[12px] font-medium text-fg-strong">Permissions</legend>
          <div className="mt-1 space-y-1.5">
            {scopes.map((s) => (
              <label key={s} className="flex items-start gap-2 text-[12.5px]"><input type="checkbox" className="mt-0.5 accent-[#D54029]" checked={sel.includes(s)} onChange={(e) => setSel(e.target.checked ? [...sel, s] : sel.filter((x) => x !== s))} />
                <span><Mono className="text-[12px]">{s}</Mono><span className="block text-2xs text-fg-muted">{SCOPE_HELP[s] ?? ""}</span></span></label>
            ))}
          </div>
        </fieldset>
        <Field label="Expires after"><Select value={days} onChange={(e) => setDays(e.target.value)} options={[{ value: "30", label: "30 days" }, { value: "90", label: "90 days" }, { value: "365", label: "1 year" }, { value: "730", label: "2 years" }]} /></Field>
        {m.error ? <ErrorBox error={m.error} compact /> : null}
      </div>
    </Dialog>
  );
}
