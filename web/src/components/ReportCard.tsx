import type { Report } from '../lib/api'

function Axis({ label, axis }: { label: string; axis: { score: number; rationale: string } }) {
  return (
    <div className="ide-axis">
      <div className="ide-axis-head">
        <strong>{label}</strong>
        <span className="ide-score">{axis.score}/5</span>
      </div>
      <p>{axis.rationale}</p>
    </div>
  )
}

function PrdList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
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
        <Axis label="Viability" axis={scorecard.viability} />
        <Axis label="Complexity" axis={scorecard.complexity} />
        <Axis label="Economic moat" axis={scorecard.economic_moat} />
        <Axis label="Market fit" axis={scorecard.market_fit} />
      </div>
      <p>
        <strong>Build vs buy:</strong> {scorecard.build_vs_buy}
      </p>
      {scorecard.competitors.length > 0 && (
        <>
          <h3>Competitors</h3>
          <ul>
            {scorecard.competitors.map((c, i) => (
              <li key={i}>
                <strong>{c.name}</strong>
                {c.url ? ` (${c.url})` : ''} — {c.note}
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>High-level PRD</h2>
      <p>
        <strong>Problem:</strong> {prd.problem}
      </p>
      <PrdList label="Target users" items={prd.target_users} />
      <PrdList label="Workflows" items={prd.workflows} />
      <PrdList label="Data entities" items={prd.data_entities} />
      <PrdList label="Capabilities" items={prd.capabilities} />
      <PrdList label="Out of scope" items={prd.out_of_scope} />
    </section>
  )
}
