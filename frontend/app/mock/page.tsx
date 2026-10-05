"use client";
import { useEffect, useState } from "react";
import { api, MockShipment } from "@/lib/api";
import { Badge, Btn, Card, ErrorMsg } from "@/components/ui";

const CARRIER_NAMES: Record<string, string> = { fastship: "FastShip", quickexpress: "QuickExpress", reliablecourier: "ReliableCourier" };

export default function MockControl() {
  const [rows, setRows] = useState<MockShipment[]>([]);
  const [chaos, setChaos] = useState<Record<string, { failure: boolean; delay_ms: number }>>({});
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<any>(null);

  const load = () => {
    api<MockShipment[]>("/mock/shipments").then(setRows).catch((e) => setError(e.message));
    api("/mock/config").then(setChaos).catch(() => {});
  };
  useEffect(() => { load(); const i = setInterval(load, 3000); return () => clearInterval(i); }, []);

  async function trigger(s: MockShipment, qs = "") {
    setError(null);
    try {
      setLast(await api(`/mock/${s.carrier}/shipments/${s.trackingNumber}/next-status${qs}`, { method: "POST" }));
      load();
    } catch (e: any) { setError(e.message); }
  }
  async function configure(carrier: string, failure: boolean, delay: number) {
    await api(`/mock/${carrier}/config?failure=${failure}&delay=${delay}`, { method: "PUT" });
    load();
  }

  return (
    <>
      <ErrorMsg error={error} />
      <Card title="Carrier shipments (carrier-side state)">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th>Carrier</th><th>Tracking number</th><th>Current</th><th>Next</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.trackingNumber} className="border-t">
                <td className="py-2">{CARRIER_NAMES[s.carrier] ?? s.carrier}</td>
                <td className="font-mono">{s.trackingNumber}</td>
                <td><Badge status={s.currentStatus} /></td>
                <td>{s.nextStatus ? <Badge status={s.nextStatus} /> : <span className="text-slate-400">—</span>}</td>
                <td className="space-x-2 whitespace-nowrap">
                  <Btn disabled={!s.nextStatus} onClick={() => trigger(s)}>Trigger Next Status</Btn>
                  {s.currentStatus === "OUT_FOR_DELIVERY" && <Btn className="!bg-red-600" onClick={() => trigger(s, "?event=delivery_failed")}>Fail delivery</Btn>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="py-4 text-slate-500">No shipments booked yet.</td></tr>}
          </tbody>
        </table>
        {last && <pre className="mt-3 max-h-48 overflow-auto rounded bg-slate-900 p-3 text-xs text-green-300">{JSON.stringify(last, null, 2)}</pre>}
      </Card>

      <Card title="Simulate unreliable carriers">
        <div className="grid gap-3 md:grid-cols-3">
          {["fastship", "quickexpress", "reliablecourier"].map((c) => {
            const cfg = chaos[c] ?? { failure: false, delay_ms: 0 };
            return (
              <div key={c} className="rounded border p-3 text-sm">
                <div className="mb-2 font-medium">{CARRIER_NAMES[c]}</div>
                <label className="mr-3"><input type="checkbox" checked={cfg.failure} onChange={(e) => configure(c, e.target.checked, cfg.delay_ms)} /> fail (HTTP 500)</label>
                <label><input type="checkbox" checked={cfg.delay_ms > 0} onChange={(e) => configure(c, cfg.failure, e.target.checked ? 3000 : 0)} /> slow (3s)</label>
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}
