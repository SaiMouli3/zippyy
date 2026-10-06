import { orderSchema } from './CreateOrder'

const valid = {
  merchantId: 'MRC-100', merchantOrderId: 'M-1',
  customer: { name: 'Rahul', phone: '9876543210', email: '' },
  pickupAddress: { addressLine1: 'a', city: 'c', state: 's', pincode: '560001' },
  deliveryAddress: { addressLine1: 'a', city: 'c', state: 's', pincode: '110001' },
  package: { weightGrams: 1500, lengthCm: 20, widthCm: 15, heightCm: 10 },
  paymentType: 'COD', codAmount: 2500,
}

describe('order form schema (mirrors backend validation)', () => {
  it('accepts a valid COD order', () => { expect(orderSchema.safeParse(valid).success).toBe(true) })
  it('rejects COD with zero amount', () => {
    const r = orderSchema.safeParse({ ...valid, codAmount: 0 })
    expect(r.success).toBe(false)
  })
  it('allows prepaid with zero amount', () => { expect(orderSchema.safeParse({ ...valid, paymentType: 'PREPAID', codAmount: 0 }).success).toBe(true) })
  it('rejects invalid phone and pincode', () => {
    expect(orderSchema.safeParse({ ...valid, customer: { ...valid.customer, phone: '12345' } }).success).toBe(false)
    expect(orderSchema.safeParse({ ...valid, deliveryAddress: { ...valid.deliveryAddress, pincode: '0123' } }).success).toBe(false)
  })
  it('rejects non-positive package values', () => {
    expect(orderSchema.safeParse({ ...valid, package: { ...valid.package, weightGrams: 0 } }).success).toBe(false)
  })
})
