import type { Report } from '../lib/api'

function scoreColor(score: number): string {
  if (score >= 4) return 'good'
  if (score === 3) return 'mid'
  return 'weak'
}

function ViabilityIcon() {
  return (
    <svg className="ide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  )
}

function ComplexityIcon() {
  return (
    <svg className="ide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 12h18" />
      <path d="M3 6h18" />
      <path d="M3 18h18" />
      <circle cx="6" cy="12" r="1.5" fill="currentColor" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      <circle cx="18" cy="12" r="1.5" fill="currentColor" />
    </svg>
  )
}

function EconomicMoatIcon() {
  return (
    <svg className="ide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2l8 4v7c0 4-4 6-8 8-4-2-8-4-8-8V6l8-4z" />
      <path d="M12 8l3 3-3 3-3-3 3-3z" />
    </svg>
  )
}

function MarketFitIcon() {
  return (
    <svg className="ide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 6 13 16 8 11 2 17" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  )
}

function Axis({ label, axis, icon }: { label: string; axis: { score: number; rationale: string }; icon: React.ReactNode }) {
  const colorClass = scoreColor(axis.score)
  return (
    <div className="ide-axis">
      <div className="ide-axis-head">
        <div className="ide-axis-label">
          {icon}
          <strong>{label}</strong>
        </div>
        <span className={`ide-score ide-score--${colorClass}`}>{axis.score}/5</span>
      </div>
      <p>{axis.rationale}</p>
    </div>
  )
}

function PrdList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="ide-report-block">
      <strong>{label}:</strong>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  )
}

export function ReportCard({ report }: { report: Report }) {
  const { prd, scorecard } = report
  return (
    <section className="ide-report">
      <h2>Viability scorecard</h2>
      <p className="ide-summary">{scorecard.summary}</p>
      <div className="ide-axes">
        <Axis label="Viability" axis={scorecard.viability} icon={<ViabilityIcon />} />
        <Axis label="Complexity" axis={scorecard.complexity} icon={<ComplexityIcon />} />
        <Axis label="Economic moat" axis={scorecard.economic_moat} icon={<EconomicMoatIcon />} />
        <Axis label="Market fit" axis={scorecard.market_fit} icon={<MarketFitIcon />} />
      </div>
      <div className="ide-report-block">
        <strong>Build vs buy:</strong> {scorecard.build_vs_buy}
      </div>
      {scorecard.competitors.length > 0 && (
        <div className="ide-report-block">
          <h3>Competitors</h3>
          <ul>
            {scorecard.competitors.map((c, i) => (
              <li key={i}>
                <strong>{c.name}</strong>
                {c.url ? ` (${c.url})` : ''} — {c.note}
              </li>
            ))}
          </ul>
        </div>
      )}

      <h2>High-level PRD</h2>
      <div className="ide-report-block">
        <strong>Problem:</strong> {prd.problem}
      </div>
      <PrdList label="Target users" items={prd.target_users} />
      <PrdList label="Workflows" items={prd.workflows} />
      <PrdList label="Data entities" items={prd.data_entities} />
      <PrdList label="Capabilities" items={prd.capabilities} />
      <PrdList label="Out of scope" items={prd.out_of_scope} />
    </section>
  )
}
