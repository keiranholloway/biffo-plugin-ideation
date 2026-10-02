import type { CostSummary } from '../lib/api'

/** A cost for display. A null cost is "unpriced", never $0. */
export function formatUsd(v: number | null | undefined): string {
  return v === null || v === undefined ? 'unpriced' : `$${v.toFixed(4)}`
}

/** A session total: the priced sum, with unpriced runs flagged beside it. */
export function formatCost(c: CostSummary | null): string {
  if (!c) return '—'
  const total = c.total_cost_usd === null ? 'unpriced' : `$${c.total_cost_usd.toFixed(4)}`
  return c.unpriced_runs > 0
    ? `${total} (${c.unpriced_runs} unpriced run${c.unpriced_runs === 1 ? '' : 's'})`
    : total
}
