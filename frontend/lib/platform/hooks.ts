"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** Filters live in the URL so operators can share links and reload without losing their place. */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const state = useMemo(() => {
    const out = { ...defaults } as Record<string, string>;
    for (const k of Object.keys(defaults)) out[k] = params.get(k) ?? defaults[k];
    return out as T;
  }, [params, defaults]);

  const set = useCallback(
    (patch: Partial<T>, opts: { resetPage?: boolean } = { resetPage: true }) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === null || v === "" || v === defaults[k]) next.delete(k);
        else next.set(k, String(v));
      }
      if (opts.resetPage && !("page" in patch)) next.delete("page");
      const s = next.toString();
      router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
    },
    [params, router, pathname, defaults],
  );

  const clear = useCallback(() => router.replace(pathname, { scroll: false }), [router, pathname]);
  const active = Object.keys(defaults).filter((k) => !["page", "pageSize", "sort", "order", "range"].includes(k) && state[k] !== defaults[k]).length;
  return { state, set, clear, active };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Re-render every `ms` so relative timestamps ("3 min ago") stay honest. */
export function useNow(ms = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function useOnClickOutside(ref: React.RefObject<HTMLElement>, onOutside: () => void) {
  const cb = useRef(onOutside);
  cb.current = onOutside;
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) cb.current();
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref]);
}

export function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) setValue(JSON.parse(raw));
    } catch {
      /* storage unavailable: keep defaults */
    }
  }, [key]);
  const set = useCallback((v: T) => {
    setValue(v);
    try {
      window.localStorage.setItem(key, JSON.stringify(v));
    } catch {
      /* ignore */
    }
  }, [key]);
  return [value, set];
}
