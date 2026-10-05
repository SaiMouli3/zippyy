import { render, screen } from '@testing-library/react'
import { Badge, StatusBadge } from './ui'

describe('status badges', () => {
  it('renders a readable label (never colour alone)', () => {
    render(<StatusBadge status="OUT_FOR_DELIVERY" />)
    expect(screen.getByText('Out for delivery')).toBeInTheDocument()
  })
  it('renders arbitrary badge content', () => {
    render(<Badge tone="ok">Cheapest</Badge>)
    expect(screen.getByText('Cheapest')).toBeInTheDocument()
  })
})
