const IST = "Asia/Kolkata";

export function money(paise: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (paise === null || paise === undefined) return "—";
  const rupees = paise / 100;
  if (opts.compact && Math.abs(rupees) >= 100000) {
    return "₹" + new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(rupees);
  }
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: rupees % 1 ? 2 : 0 }).format(rupees);
}

export function num(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(n);
}

export function pct(r: number | null | undefined, digits = 1): string {
  if (r === null || r === undefined || Number.isNaN(r)) return "—";
  return `${(r * 100).toFixed(digits)}%`;
}

export function absolute(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined, hour12: false,
  }).format(new Date(iso)) + " IST";
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T00:00:00+05:30") : new Date(iso);
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, weekday: "short", day: "2-digit", month: "short" }).format(d);
}

export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [[86400000, "day"], [3600000, "hour"], [60000, "minute"]];
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "short" });
  for (const [ms, unit] of units) if (abs >= ms) return rtf.format(Math.round(diff / ms), unit);
  return diff < 0 ? "just now" : "in <1 min";
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export function hoursLeft(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return (new Date(iso).getTime() - Date.now()) / 3600000;
}

export function window_(w: string | null | undefined): string {
  return w ? w.replace("-", "–") : "";
}

export function short(id: string | null | undefined, n = 8): string {
  return id ? id.slice(-n) : "—";
}
