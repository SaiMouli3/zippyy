"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "@/lib/platform/api";

// ------------------------------------------------------------------ session
export interface Me {
  user: { id: string; email: string; name: string };
  merchantId: string;
  role: string;
  permissions: string[];
  memberships: { merchantId: string; code: string; brandName: string; role: string; isDemo: boolean }[];
  isDemo: boolean;
}

const SessionCtx = createContext<{ me: Me; can: (p: string) => boolean } | null>(null);

export function useSession() {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}

function SessionGate({ children }: { children: ReactNode }) {
  const q = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me"), staleTime: 60_000, retry: false });
  const value = useMemo(() => (q.data ? { me: q.data, can: (p: string) => q.data!.permissions.includes(p) } : null), [q.data]);
  if (q.isError) {
    const e = q.error as ApiError;
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas p-6 text-center">
        <div>
          <p className="font-heading text-[16px] font-bold text-fg-strong">{e.status === 401 ? "Your session has ended" : "Couldn't load your workspace"}</p>
          <p className="mt-1 text-[13px] text-fg-muted">{e.message}</p>
          <a href="/login" className="mt-4 inline-block rounded-md bg-zy-brand px-4 py-2 text-[13px] font-medium text-white">Sign in</a>
        </div>
      </div>
    );
  }
  if (!value) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zy-ink" role="status" aria-label="Loading workspace">
        <img src="/brand/logo-on-dark.svg" alt="Zippyy" className="h-9 w-auto animate-pulse2" />
      </div>
    );
  }
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

// ------------------------------------------------------------------ live events
export type LiveState = "connecting" | "live" | "reconnecting" | "offline";
export interface LiveEvent { id: string; type: string; aggregate: string; entityId: string; payload: Record<string, unknown>; at: string }

const LiveCtx = createContext<{ state: LiveState; lastBeat: number | null; events: LiveEvent[]; pollMs: number | false }>({
  state: "connecting", lastBeat: null, events: [], pollMs: 30000,
});

export function useLive() {
  return useContext(LiveCtx);
}

/** Polling interval for server state: off while the event stream is healthy, 30 s otherwise. */
export function usePoll(): number | false {
  return useLive().pollMs;
}

const KEYS_FOR: Record<string, string[][]> = {
  ndr_case: [["ndr"], ["case"], ["dashboard"], ["queues"]],
  escalation: [["escalations"], ["case"], ["ndr"], ["dashboard"], ["queues"]],
  message: [["conversations"], ["case"], ["ndr"]],
  voice_call: [["calls"], ["case"], ["ndr"]],
  carrier_action: [["case"], ["ndr"], ["carrier-actions"], ["queues"]],
  agent_task: [["agent-runs"], ["case"], ["ndr"], ["pre-delivery"]],
  shipment: [["shipments"], ["case"], ["dashboard"]],
};

function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveState>("connecting");
  const [lastBeat, setLastBeat] = useState<number | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const pending = useRef<Set<string>>(new Set());
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const schedule = useCallback((aggregate: string) => {
    for (const k of KEYS_FOR[aggregate] ?? [["ndr"]]) pending.current.add(JSON.stringify(k));
    if (flushTimer.current) return;
    flushTimer.current = setTimeout(() => {
      // Coalesce bursts: one invalidation per query family per second.
      pending.current.forEach((k) => qc.invalidateQueries({ queryKey: JSON.parse(k) }));
      pending.current.clear();
      flushTimer.current = null;
    }, 900);
  }, [qc]);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const seen = new Set<string>();

    function connect() {
      if (closed) return;
      es = new EventSource("/api/v1/events/stream");
      es.addEventListener("hello", () => { attempts = 0; setState("live"); setLastBeat(Date.now()); });
      es.addEventListener("heartbeat", () => { setState("live"); setLastBeat(Date.now()); });
      es.addEventListener("resync", () => qc.invalidateQueries());
      es.addEventListener("update", (msg) => {
        const ev = msg as MessageEvent;
        if (seen.has(ev.lastEventId)) return; // duplicates after reconnect
        seen.add(ev.lastEventId);
        if (seen.size > 2000) seen.clear();
        setLastBeat(Date.now());
        try {
          const d = JSON.parse(ev.data);
          const item: LiveEvent = { id: ev.lastEventId, type: d.type, aggregate: d.aggregate, entityId: d.id, payload: d.payload ?? {}, at: d.at };
          setEvents((prev) => [item, ...prev].slice(0, 60));
          schedule(d.aggregate);
        } catch {
          /* malformed event: ignore, the next refetch reconciles */
        }
      });
      es.onerror = () => {
        es?.close();
        if (closed) return;
        attempts += 1;
        setState(attempts > 3 ? "offline" : "reconnecting");
        retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempts));
      };
    }
    connect();
    const watchdog = setInterval(() => {
      setLastBeat((b) => {
        if (b && Date.now() - b > 35000) setState((s) => (s === "live" ? "reconnecting" : s));
        return b;
      });
    }, 5000);
    return () => { closed = true; es?.close(); if (retry) clearTimeout(retry); clearInterval(watchdog); };
  }, [qc, schedule]);

  const value = useMemo(() => ({ state, lastBeat, events, pollMs: (state === "live" ? false : 30000) as number | false }), [state, lastBeat, events]);
  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}

export function PlatformProviders({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retry: (count, err) => !(err instanceof ApiError && [401, 403, 404, 422].includes(err.status)) && count < 2,
      },
    },
  }));
  return (
    <QueryClientProvider client={client}>
      <SessionGate>
        <LiveProvider>{children}</LiveProvider>
      </SessionGate>
    </QueryClientProvider>
  );
}
