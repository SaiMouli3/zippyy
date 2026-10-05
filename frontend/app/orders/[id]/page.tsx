"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Order } from "@/lib/api";
import { Badge, Card, ErrorMsg } from "@/components/ui";

export default function OrderDetails({ params }: { params: { id: string } }) {
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Order>(`/api/orders/${params.id}`).then(setOrder).catch((e) => setError(e.message)); }, [params.id]);

  if (!order) return <ErrorMsg error={error ?? "Loading…"} />;
  const rows: [string, string][] = [
    ["Order ID", order.id], ["Merchant order", order.merchantOrderId], ["Customer", `${order.customerName} (${order.customerPhone})`],
    ["Route", `${order.pickupPincode} → ${order.deliveryPincode}`], ["Weight", `${order.weightGrams} g`],
    ["Payment", order.paymentType === "COD" ? `COD ₹${order.codAmount}` : "Prepaid"],
  ];
  return (
    <>
      <Card title="Order details">
        <p className="mb-3">Status: <Badge status={order.status} /></p>
        <dl className="grid grid-cols-[10rem_1fr] gap-y-1 text-sm">
          {rows.map(([k, v]) => (<div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd>{v}</dd></div>))}
        </dl>
      </Card>
      <div className="flex gap-3 text-sm">
        <Link className="rounded border bg-white px-3 py-1.5 hover:bg-slate-100" href={`/orders/${order.id}/rates`}>Shipping options →</Link>
        <Link className="rounded border bg-white px-3 py-1.5 hover:bg-slate-100" href={`/orders/${order.id}/tracking`}>Tracking →</Link>
      </div>
    </>
  );
}
