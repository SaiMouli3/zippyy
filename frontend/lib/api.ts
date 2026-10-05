export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : d?.message ?? (Array.isArray(d) ? d.map((e: any) => `${e.loc?.slice(-1)}: ${e.msg}`).join("; ") : res.statusText);
    throw new ApiError(msg);
  }
  return body as T;
}

export type Order = {
  id: string; merchantId: string; merchantOrderId: string; customerName: string; customerPhone: string;
  pickupPincode: string; deliveryPincode: string; weightGrams: number; paymentType: string; codAmount: number;
  status: string; createdAt: string;
};
export type ShippingOption = {
  quoteId: string; carrierCode: string; carrierName: string; serviceCode: string; serviceName: string;
  baseCharge: number; codCharge: number; additionalCharges: number; tax: number; totalCharge: number;
  estimatedMinDays: number | null; estimatedMaxDays: number | null; expiresAt: string;
};
export type Rates = {
  orderId: string; shippingOptions: ShippingOption[];
  failedCarriers: { carrierCode: string; carrierName: string; reason: string }[]; cached: boolean;
};
export type Tracking = {
  trackingNumber: string; carrier: string; currentStatus: string;
  history: { status: string; timestamp: string; location?: string; description?: string }[];
};
export type MockShipment = {
  carrier: string; trackingNumber: string; carrierShipmentId: string; currentStatus: string; nextStatus: string | null;
};
