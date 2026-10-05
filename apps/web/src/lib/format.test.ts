import { bestValue, days, maskPhone, money, pretty } from './format'

describe('format helpers', () => {
  it('formats rupees with two decimals', () => { expect(money(182.9)).toBe('₹182.90') })
  it('formats ETA ranges', () => {
    expect(days(2, 2)).toBe('2 days')
    expect(days(4, 5)).toBe('4–5 days')
    expect(days(1, 1)).toBe('1 day')
  })
  it('masks phone numbers', () => { expect(maskPhone('9876543210')).toBe('XXXXXX3210') })
  it('prettifies enum names', () => { expect(pretty('OUT_FOR_DELIVERY')).toBe('Out for delivery') })
  it('picks a balanced best-value option', () => {
    const o = [
      { totalCharge: 159.3, estimatedMinDays: 4, estimatedMaxDays: 5 },
      { totalCharge: 182.9, estimatedMinDays: 2, estimatedMaxDays: 2 },
      { totalCharge: 197.06, estimatedMinDays: 2, estimatedMaxDays: 3 },
    ]
    expect(bestValue(o)?.totalCharge).toBe(182.9)
    expect(bestValue([])).toBeUndefined()
  })
})
