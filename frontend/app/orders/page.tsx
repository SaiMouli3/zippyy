"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Order } from "@/lib/api";
import { Badge, Btn, Card, ErrorMsg } from "@/components/ui";

const blank = { customerName: "Asha Rao", customerPhone: "9876543210", pickupPincode: "560001", deliveryPincode: "500001", weightGrams: 2000, paymentType: "COD", codAmount: 2000 };

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [form, setForm] = useState(blank);
  const [error, setError] = useState<string | null>(null);

  const load = () => api<Order[]>("/api/orders").then(setOrders).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/orders", { method: "POST", body: JSON.stringify({ ...form, codAmount: form.paymentType === "COD" ? form.codAmount : 0 }) });
      load();
    } catch (err: any) { setError(err.message); }
  }

  const input = "w-full rounded border px-2 py-1 text-sm";
  const set = (k: string, num = false) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: num ? Number(e.target.value) : e.target.value });

  return (
    <>
      <Card title="New order">
        <ErrorMsg error={error} />
        <form onSubmit={create} className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <label className="text-xs">Customer<input className={input} value={form.customerName} onChange={set("customerName")} /></label>
          <label className="text-xs">Phone<input className={input} value={form.customerPhone} onChange={set("customerPhone")} /></label>
          <label className="text-xs">Pickup pincode<input className={input} value={form.pickupPincode} onChange={set("pickupPincode")} /></label>
          <label className="text-xs">Delivery pincode<input className={input} value={form.deliveryPincode} onChange={set("deliveryPincode")} /></label>
          <label className="text-xs">Weight (g)<input type="number" className={input} value={form.weightGrams} onChange={set("weightGrams", true)} /></label>
          <label className="text-xs">Payment
            <select className={input} value={form.paymentType} onChange={set("paymentType")}><option>COD</option><option>PREPAID</option></select>
          </label>
          {form.paymentType === "COD" && <label className="text-xs">COD amount<input type="number" className={input} value={form.codAmount} onChange={set("codAmount", true)} /></label>}
          <div className="flex items-end"><Btn type="submit">Create order</Btn></div>
        </form>
      </Card>

      <Card title="Orders">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th>Order</th><th>Route</th><th>Weight</th><th>Payment</th><th>Status</th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id} className="border-t">
                <td className="py-2"><Link className="text-indigo-600 hover:underline" href={`/orders/${o.id}`}>{o.merchantOrderId}</Link><div className="text-xs text-slate-500">{o.customerName}</div></td>
                <td>{o.pickupPincode} → {o.deliveryPincode}</td>
                <td>{o.weightGrams / 1000} kg</td>
                <td>{o.paymentType}{o.paymentType === "COD" ? ` ₹${o.codAmount}` : ""}</td>
                <td><Badge status={o.status} /></td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={5} className="py-4 text-slate-500">No orders yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </>
  );
}
