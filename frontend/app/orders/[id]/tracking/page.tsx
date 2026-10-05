"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Tracking } from "@/lib/api";
import { Badge, Btn, Card, ErrorMsg } from "@/components/ui";

export default function TrackingPage({ params }: { params: { id: string } }) {
  const [t, setT] = useState<Tracking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api<Tracking>(`/api/orders/${params.id}/tracking`).then((d) => { setT(d); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => { load(); const i = setInterval(load, 3000); return () => clearInterval(i); }, [params.id]);

  return (
    <Card title="Shipment tracking">
      <ErrorMsg error={error} />
      <div className="mb-4 flex items-center gap-3">
        <Btn onClick={load}>Refresh</Btn>
        <span className="text-xs text-slate-500">auto-refreshes every 3s</span>
        <Link href={`/orders/${params.id}`} className="ml-auto text-sm text-indigo-600">← Order</Link>
      </div>
      {t && (
        <>
          <p className="mb-4 text-sm">{t.carrier} · <span className="font-mono">{t.trackingNumber}</span> · <Badge status={t.currentStatus} /></p>
          <ol className="border-l-2 border-indigo-200 pl-4">
            {t.history.map((h, i) => (
              <li key={i} className="mb-3">
                <div className="text-sm font-medium">{h.status}</div>
                <div className="text-xs text-slate-500">{new Date(h.timestamp).toLocaleString()} {h.location ? `· ${h.location}` : ""}</div>
                {h.description && <div className="text-xs text-slate-500">{h.description}</div>}
              </li>
            ))}
          </ol>
        </>
      )}
    </Card>
  );
}
