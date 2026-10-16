"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, Rates } from "@/lib/api";
import { Btn, Card, ErrorMsg, eta } from "@/components/ui";

export default function ShippingOptions({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [rates, setRates] = useState<Rates | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true); setError(null);
    try { return await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  const fetchRates = (refresh: boolean) => run(async () => setRates(await api<Rates>(`/api/orders/${params.id}/rates${refresh ? "?refresh=true" : ""}`, { method: "POST" })));

  const book = (o: Rates["shippingOptions"][number]) => run(async () => {
    await api(`/api/orders/${params.id}/select-carrier`, { method: "POST", body: JSON.stringify({ carrierCode: o.carrierCode, serviceCode: o.serviceCode, quotedAmount: o.totalCharge }) });
    await api(`/api/orders/${params.id}/shipment`, { method: "POST" });
    router.push(`/orders/${params.id}/tracking`);
  });

  return (
    <Card title="Shipping options">
      <ErrorMsg error={error} />
      <div className="mb-4 flex items-center gap-3">
        <Btn disabled={busy} onClick={() => fetchRates(false)}>Get rates</Btn>
        <Btn disabled={busy} onClick={() => fetchRates(true)} className="!bg-slate-600">Refresh (skip cache)</Btn>
        {rates && <span className={`text-xs ${rates.cached ? "text-green-700" : "text-slate-500"}`}>{rates.cached ? "served from Redis cache" : "fetched live from carriers"}</span>}
        <Link href={`/orders/${params.id}`} className="ml-auto text-sm text-indigo-600">← Order</Link>
      </div>
      {rates?.failedCarriers.map((f) => (<p key={f.carrierCode} className="mb-2 rounded bg-amber-50 p-2 text-sm text-amber-800">{f.carrierName} unavailable: {f.reason}</p>))}
      {rates && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th>Carrier / service</th><th>Base</th><th>COD</th><th>Other</th><th>Tax</th><th>Total</th><th>ETA</th><th /></tr></thead>
          <tbody>
            {rates.shippingOptions.map((o) => (
              <tr key={o.quoteId} className="border-t">
                <td className="py-2">{o.carrierName}<div className="text-xs text-slate-500">{o.serviceName}</div></td>
                <td>₹{o.baseCharge}</td><td>₹{o.codCharge}</td><td>₹{o.additionalCharges}</td><td>₹{o.tax}</td>
                <td className="font-semibold">₹{o.totalCharge}</td><td>{eta(o.estimatedMinDays, o.estimatedMaxDays)}</td>
                <td><Btn disabled={busy} onClick={() => book(o)}>Book</Btn></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
