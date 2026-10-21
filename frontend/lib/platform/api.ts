// Typed client for the v1 API. Same-origin (proxied by Next), cookie session, CSRF header on unsafe methods.
export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  fields?: { loc: string[]; msg: string }[];

  constructor(status: number, code: string, message: string, requestId?: string, fields?: { loc: string[]; msg: string }[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)zpy_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export function qs(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    p.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}${qs(opts.query)}`, {
      method, headers, credentials: "same-origin", signal: opts.signal, cache: "no-store",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK", "Can't reach the Zippyy API. Check your connection and retry.");
  }
  const requestId = res.headers.get("x-request-id") ?? undefined;
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = res.statusText || "Request failed";
    let fields: { loc: string[]; msg: string }[] | undefined;
    try {
      const data = await res.json();
      const d = data?.detail;
      if (Array.isArray(d)) {
        code = "VALIDATION";
        fields = d;
        message = d.map((x: { loc?: string[]; msg?: string }) => `${(x.loc ?? []).slice(1).join(".") || "input"}: ${x.msg}`).join("; ");
      } else if (d && typeof d === "object") {
        code = d.code ?? code;
        message = d.message ?? message;
      } else if (typeof d === "string") {
        message = d;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message, requestId, fields);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  generatedAt: string;
}
