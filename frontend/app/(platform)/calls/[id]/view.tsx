"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRightLeft, FileText, Lock, VolumeX } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { usePoll, useSession } from "@/components/platform/providers";
import { Badge, Button, cx, ErrorBox, KeyValue, LangTag, Mono, Notice, Panel, PanelHeader, Skeleton, StatusBadge, Timestamp } from "@/components/platform/ui";
import { api, ApiError } from "@/lib/platform/api";
import { absolute, dateOnly, duration, money, pct, window_ } from "@/lib/platform/format";
import { CALL_RESULT, CALL_STATUS, LANG, title } from "@/lib/platform/labels";
import type { CallItem, Transcript } from "@/lib/platform/types";

export function CallView() {
  const { id } = useParams<{ id: string }>();
  const poll = usePoll();
  const { can } = useSession();
  const [showTranscript, setShowTranscript] = useState(false);
  const [english, setEnglish] = useState(false);
  const q = useQuery({ queryKey: ["calls", id], queryFn: () => api<CallItem>(`/voice-calls/${id}`), refetchInterval: poll });
  const t = useQuery({ queryKey: ["calls", id, "transcript"], queryFn: () => api<Transcript>(`/voice-calls/${id}/transcript`), enabled: showTranscript, staleTime: Infinity });
  const back = <Link href="/calls" className="inline-flex items-center gap-1 text-[12.5px] text-fg-muted hover:text-fg-strong"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Voice calls</Link>;
  if (q.isError) return <div className="space-y-3">{back}<Panel>{(q.error as ApiError).status === 404 ? <p className="px-6 py-14 text-center text-[13px] text-fg-muted">Call not found in this workspace.</p> : <ErrorBox error={q.error} onRetry={() => q.refetch()} />}</Panel></div>;
  if (!q.data) return <div className="space-y-4">{back}<Skeleton className="h-8 w-64" /><Skeleton className="h-96 w-full" /></div>;
  const c = q.data;
  const switches = (c.events ?? []).filter((e) => e.kind === "language_switch");
  const hasTranslation = t.data?.turns.some((x) => x.textEn && x.textEn !== x.text);

  return (
    <div className="space-y-4">
      {back}
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="font-mono text-[20px] font-semibold tracking-tight text-fg-strong">{c.code}</h1>
        <StatusBadge map={CALL_STATUS} value={c.status} />
        {c.result && <StatusBadge map={CALL_RESULT} value={c.result} />}
        {c.provider === "simulator" && <Badge tone="warn" dot={false}>Simulated call</Badge>}
        <span className="text-[12.5px] text-fg-muted">{title(c.purpose)} · attempt {c.attemptNo} · {c.customerName} <Mono className="text-[12px] text-fg-muted">{c.phoneMasked}</Mono></span>
      </header>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel className="min-w-0">
          <PanelHeader title="Transcript" subtitle="What was said, turn by turn, with the language detected for each turn"
            actions={showTranscript && hasTranslation ? (
              <label className="flex items-center gap-1.5 text-[12px] text-fg"><input type="checkbox" checked={english} onChange={(e) => setEnglish(e.target.checked)} className="accent-[#D54029]" />Show English translation</label>
            ) : null} />
          <div className="px-4 py-4">
            {!can("transcripts.read") ? (
              <p className="flex items-center gap-2 text-[12.5px] text-fg-muted"><Lock className="h-3.5 w-3.5" aria-hidden />Your role cannot read call transcripts.</p>
            ) : !c.transcriptAvailable ? (
              <p className="text-[12.5px] text-fg-muted">{["completed"].includes(c.status) ? "The provider did not return a transcript for this call." : "No conversation took place on this call."}</p>
            ) : !showTranscript ? (
              <div className="flex flex-col items-start gap-2">
                <p className="text-[12.5px] text-fg-muted">Transcripts contain what the customer said. Opening one is recorded in the audit log.</p>
                <Button variant="dark" icon={<FileText className="h-3.5 w-3.5" />} onClick={() => setShowTranscript(true)}>Open transcript</Button>
              </div>
            ) : t.isError ? <ErrorBox error={t.error} compact /> : !t.data ? <Skeleton className="h-60 w-full" /> : !t.data.available ? (
              <Notice>{t.data.reason ?? "Transcript unavailable."}</Notice>
            ) : (
              <ol className="space-y-2.5">
                {t.data.turns.map((turn) => {
                  if (turn.kind === "language_switch") {
                    return (
                      <li key={turn.seq} className="flex items-center gap-2 py-1 text-2xs font-medium text-zy-brand">
                        <span className="h-px flex-1 bg-zy-brand/30" />
                        <ArrowRightLeft className="h-3 w-3" aria-hidden /> Switched {LANG[turn.fromLanguage ?? ""] ?? turn.fromLanguage} → {LANG[turn.toLanguage ?? ""] ?? turn.toLanguage}
                        {turn.confidence !== null && <span className="font-normal text-fg-muted">({pct(turn.confidence, 0)})</span>}
                        <span className="h-px flex-1 bg-zy-brand/30" />
                      </li>
                    );
                  }
                  if (turn.kind === "silence") {
                    return <li key={turn.seq} className="flex items-center gap-2 pl-14 text-2xs italic text-fg-subtle"><VolumeX className="h-3 w-3" aria-hidden />No response from the customer</li>;
                  }
                  const agent = turn.speaker !== "customer";
                  const text = english && turn.textEn ? turn.textEn : turn.text;
                  return (
                    <li key={turn.seq} className="flex gap-3">
                      <span className="num w-11 shrink-0 pt-1 text-right text-2xs text-fg-subtle">{turn.offsetSeconds !== null ? duration(Math.round(turn.offsetSeconds)) : ""}</span>
                      <div className={cx("min-w-0 flex-1 rounded-lg border px-3 py-2", agent ? "border-line bg-zy-paper" : "border-[#C9DDFA] bg-info-soft/60")}>
                        <div className="mb-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-fg-muted">
                          <span className="font-semibold text-fg">{agent ? "Zippyy voice agent" : "Customer"}</span>
                          <LangTag code={turn.language} confirmed={!agent} />
                          {!agent && turn.confidence !== null && <span>{pct(turn.confidence, 0)}</span>}
                          {turn.codeMixed && <Badge tone="info" dot={false}>Code-mixed</Badge>}
                          {english && turn.textEn && turn.textEn !== turn.text && <span className="italic">translated</span>}
                        </div>
                        <p className="whitespace-pre-wrap break-words text-[13px] leading-5 text-fg-strong">{text}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </Panel>
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Call" />
            <div className="px-4 py-3">
              <KeyValue cols={2} items={[
                { k: "Provider", v: c.provider === "simulator" ? "Simulator" : "Sarvam" }, { k: "Provider call ID", v: c.providerCallId ? <Mono className="text-[11.5px]">{c.providerCallId}</Mono> : "—" },
                { k: "Scheduled", v: c.scheduledFor ? absolute(c.scheduledFor) : "—" }, { k: "Started", v: c.startedAt ? absolute(c.startedAt) : "—" },
                { k: "Answered", v: c.answeredAt ? absolute(c.answeredAt) : "—" }, { k: "Duration", v: duration(c.durationSeconds) },
                { k: "Provider status", v: c.providerRawStatus ?? "—" }, { k: "Cost", v: c.costPaise === null ? "Not reported" : c.provider === "simulator" ? `${money(c.costPaise)} (simulated)` : money(c.costPaise) },
              ]} />
              {c.errorMessage && <p className="mt-2 text-2xs text-danger">{c.errorCode}: {c.errorMessage}</p>}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Language" />
            <div className="space-y-2 px-4 py-3 text-[12.5px]">
              <p className="flex items-center gap-2"><span className="w-24 text-fg-subtle">Started in</span><LangTag code={c.startLanguage} /> {LANG[c.startLanguage ?? ""] ?? "—"}</p>
              <p className="flex items-center gap-2"><span className="w-24 text-fg-subtle">Ended in</span><LangTag code={c.finalLanguage} confirmed /> {LANG[c.finalLanguage ?? ""] ?? "—"}</p>
              {switches.length > 0 ? (
                <ul className="mt-1 space-y-1 border-t border-line pt-2">
                  {switches.map((s) => (
                    <li key={s.seq} className="flex items-center gap-2 text-2xs text-fg-muted">
                      <ArrowRightLeft className="h-3 w-3 text-zy-brand" aria-hidden /><LangTag code={s.fromLanguage} /> → <LangTag code={s.toLanguage} confirmed />
                      {s.confidence !== null && <span>{pct(s.confidence, 0)}</span>}{s.codeMixed && <span>code-mixed</span>}<span className="ml-auto"><Timestamp iso={s.at} mode="absolute" /></span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-2xs text-fg-muted">No language switch on this call.</p>}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="What came out of it" />
            <div className="space-y-1.5 px-4 py-3 text-[12.5px]">
              {c.intent ? <p><span className="text-fg-subtle">AI extracted</span> <span className="ml-1 font-medium text-fg-strong">{title(c.intent.intent)}</span> <span className="text-fg-muted">· {pct(c.intent.confidence, 0)}{c.intent.date ? ` · ${dateOnly(c.intent.date)}` : ""}{c.intent.window ? ` ${window_(c.intent.window)}` : ""}</span></p> : <p className="text-fg-muted">No intent extracted.</p>}
              <p><span className="text-fg-subtle">Preference captured</span> <span className="ml-1 text-fg-strong">{c.preferenceCaptured ? "Yes" : "No"}</span></p>
              <p><span className="text-fg-subtle">Follow-up scheduled</span> <span className="ml-1 text-fg-strong">{c.followupScheduled ? "Yes" : "No"}</span></p>
              {c.ndrCaseId && <Link href={`/ndr/${c.ndrCaseId}`} className="inline-block pt-1 font-medium text-zy-brand hover:underline">Open the NDR case</Link>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
