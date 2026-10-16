// Drawn stand-in for product screenshots, so the page renders without third-party images.
// Pass `src` to show a real image from public/brand/ instead.
export function MockPanel({ title, rows, tone = "dark", src }: {
  title: string; rows: [string, string][]; tone?: "dark" | "light"; src?: string;
}) {
  if (src) return <img src={src} alt={title} className="mx-auto w-full max-w-xl animate-float" />;
  const dark = tone === "dark";
  return (
    <div className={`mx-auto w-full max-w-xl animate-float rounded-2xl border p-6 shadow-zy-menu ${dark ? "border-white/10 bg-zy-ink-2" : "border-black/5 bg-white"}`}>
      <div className="mb-5 flex items-center gap-2">
        <span className="h-3 w-3 rounded-full bg-zy-brand" />
        <span className="h-3 w-3 rounded-full bg-zy-muted/50" />
        <span className="h-3 w-3 rounded-full bg-zy-muted/30" />
        <span className={`ml-3 font-heading text-sm font-semibold ${dark ? "text-white" : "text-zy-ink"}`}>{title}</span>
      </div>
      <ul className="space-y-3">
        {rows.map(([label, value], i) => (
          <li key={label} className={`flex items-center justify-between rounded-lg px-4 py-3 text-sm ${dark ? "bg-white/5 text-white/80" : "bg-zy-paper text-zy-ink-3"}`}>
            <span>{label}</span>
            <span className={i === 0 ? "font-semibold text-zy-brand" : "font-medium"}>{value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
