import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ReportCard } from './ReportCard'
import type { Report } from '../lib/api'

describe('ReportCard', () => {
  // Fixture: a complete report with varied scores to test all color classes
  const completeReportFixture: Report = {
    prd: {
      problem: 'Teams struggle to coordinate async work without context loss',
      target_users: ['Project managers', 'Remote teams'],
      workflows: ['Daily standup', 'Async updates'],
      data_entities: ['Tasks', 'Comments', 'Updates'],
      capabilities: ['Real-time sync', 'Search history'],
      out_of_scope: ['Video conferencing', 'File storage'],
    },
    scorecard: {
      viability: { score: 5, rationale: 'Clear market need, validated with 50+ teams' },
      complexity: { score: 3, rationale: 'Moderate complexity due to sync logic' },
      economic_moat: { score: 2, rationale: 'Low barrier to entry from incumbents' },
      market_fit: { score: 4, rationale: 'Strong product-market fit in remote-first companies' },
      build_vs_buy: 'Build to differentiate on async UX',
      competitors: [
        { name: 'Slack', url: 'https://slack.com', note: 'Different approach to async' },
        { name: 'Notion', note: 'Covers some workflows but lacks real-time sync' },
      ],
      summary: 'Strong opportunity in the async coordination space with clear differentiation',
    },
  }

  // Fixture: report with all scores at 3 (mid) boundary
  const midScoresFixture: Report = {
    prd: {
      problem: 'Medium-sized problem',
      target_users: ['Group A'],
      workflows: [],
      data_entities: [],
      capabilities: [],
      out_of_scope: [],
    },
    scorecard: {
      viability: { score: 3, rationale: 'Moderate viability' },
      complexity: { score: 3, rationale: 'Moderate complexity' },
      economic_moat: { score: 3, rationale: 'Moderate moat' },
      market_fit: { score: 3, rationale: 'Moderate fit' },
      build_vs_buy: 'Build',
      competitors: [],
      summary: 'All middle-of-road scores',
    },
  }

  // Fixture: report with all low scores
  const lowScoresFixture: Report = {
    prd: {
      problem: 'Low-scoring idea',
      target_users: [],
      workflows: [],
      data_entities: [],
      capabilities: [],
      out_of_scope: [],
    },
    scorecard: {
      viability: { score: 1, rationale: 'Low viability' },
      complexity: { score: 2, rationale: 'Low complexity but not valuable' },
      economic_moat: { score: 1, rationale: 'No moat' },
      market_fit: { score: 2, rationale: 'Poor fit' },
      build_vs_buy: 'Buy',
      competitors: [],
      summary: 'Weak opportunity across all dimensions',
    },
  }

  it('renders a score of 5 on Viability with the ide-score--good class', () => {
    render(<ReportCard report={completeReportFixture} />)

    // Find the Viability axis container and its score badge
    const viabilitySection = screen.getByText('Viability').closest('.ide-axis')
    expect(viabilitySection).toBeInTheDocument()

    const scoreBadge = viabilitySection?.querySelector('.ide-score')
    expect(scoreBadge).toHaveClass('ide-score--good')
    expect(scoreBadge).toHaveTextContent('5/5')
  })

  it('renders a score of 4 on Market fit with the ide-score--good class', () => {
    render(<ReportCard report={completeReportFixture} />)

    const marketFitSection = screen.getByText('Market fit').closest('.ide-axis')
    expect(marketFitSection).toBeInTheDocument()

    const scoreBadge = marketFitSection?.querySelector('.ide-score')
    expect(scoreBadge).toHaveClass('ide-score--good')
    expect(scoreBadge).toHaveTextContent('4/5')
  })

  it('renders a score of 3 on Complexity with the ide-score--mid class', () => {
    render(<ReportCard report={completeReportFixture} />)

    const complexitySection = screen.getByText('Complexity').closest('.ide-axis')
    expect(complexitySection).toBeInTheDocument()

    const scoreBadge = complexitySection?.querySelector('.ide-score')
    expect(scoreBadge).toHaveClass('ide-score--mid')
    expect(scoreBadge).toHaveTextContent('3/5')
  })

  it('renders all mid-range scores (3) with ide-score--mid class', () => {
    render(<ReportCard report={midScoresFixture} />)

    // Check all four axes have score 3 with mid class
    const viabilitySection = screen.getByText('Viability').closest('.ide-axis')
    expect(viabilitySection?.querySelector('.ide-score')).toHaveClass('ide-score--mid')

    const complexitySection = screen.getByText('Complexity').closest('.ide-axis')
    expect(complexitySection?.querySelector('.ide-score')).toHaveClass('ide-score--mid')

    const economicMoatSection = screen.getByText('Economic moat').closest('.ide-axis')
    expect(economicMoatSection?.querySelector('.ide-score')).toHaveClass('ide-score--mid')

    const marketFitSection = screen.getByText('Market fit').closest('.ide-axis')
    expect(marketFitSection?.querySelector('.ide-score')).toHaveClass('ide-score--mid')
  })

  it('renders a score of 2 on Complexity with the ide-score--weak class', () => {
    render(<ReportCard report={lowScoresFixture} />)

    const complexitySection = screen.getByText('Complexity').closest('.ide-axis')
    expect(complexitySection).toBeInTheDocument()

    const scoreBadge = complexitySection?.querySelector('.ide-score')
    expect(scoreBadge).toHaveClass('ide-score--weak')
    expect(scoreBadge).toHaveTextContent('2/5')
  })

  it('renders a score of 1 on Viability with the ide-score--weak class', () => {
    render(<ReportCard report={lowScoresFixture} />)

    const viabilitySection = screen.getByText('Viability').closest('.ide-axis')
    expect(viabilitySection).toBeInTheDocument()

    const scoreBadge = viabilitySection?.querySelector('.ide-score')
    expect(scoreBadge).toHaveClass('ide-score--weak')
    expect(scoreBadge).toHaveTextContent('1/5')
  })

  it('renders all low scores (1–2) with ide-score--weak class', () => {
    render(<ReportCard report={lowScoresFixture} />)

    // Check all four axes have low scores with weak class
    const viabilitySection = screen.getByText('Viability').closest('.ide-axis')
    expect(viabilitySection?.querySelector('.ide-score')).toHaveClass('ide-score--weak')

    const complexitySection = screen.getByText('Complexity').closest('.ide-axis')
    expect(complexitySection?.querySelector('.ide-score')).toHaveClass('ide-score--weak')

    const economicMoatSection = screen.getByText('Economic moat').closest('.ide-axis')
    expect(economicMoatSection?.querySelector('.ide-score')).toHaveClass('ide-score--weak')

    const marketFitSection = screen.getByText('Market fit').closest('.ide-axis')
    expect(marketFitSection?.querySelector('.ide-score')).toHaveClass('ide-score--weak')
  })

  it('renders all four axis labels: Viability, Complexity, Economic moat, Market fit', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Viability')).toBeInTheDocument()
    expect(screen.getByText('Complexity')).toBeInTheDocument()
    expect(screen.getByText('Economic moat')).toBeInTheDocument()
    expect(screen.getByText('Market fit')).toBeInTheDocument()
  })

  it('renders an icon for each axis within its container', () => {
    render(<ReportCard report={completeReportFixture} />)

    const axes = screen.getAllByText(/^(Viability|Complexity|Economic moat|Market fit)$/)
    expect(axes).toHaveLength(4)

    // Each label should have an icon (SVG) in its parent axis container
    axes.forEach((label) => {
      const axisContainer = label.closest('.ide-axis')
      const icon = axisContainer?.querySelector('.ide-icon')
      expect(icon).toBeInTheDocument()
      expect(icon?.tagName.toLowerCase()).toBe('svg')
    })
  })

  it('renders the summary text from the scorecard', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Strong opportunity in the async coordination space with clear differentiation')).toBeInTheDocument()
  })

  it('renders the build vs buy section', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText(/Build to differentiate on async UX/)).toBeInTheDocument()
  })

  it('renders competitors when present', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Slack')).toBeInTheDocument()
    expect(screen.getByText('Notion')).toBeInTheDocument()
    expect(screen.getByText(/Different approach to async/)).toBeInTheDocument()
    expect(screen.getByText(/Covers some workflows but lacks real-time sync/)).toBeInTheDocument()
  })

  it('renders the PRD section with problem statement', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText(/Teams struggle to coordinate async work without context loss/)).toBeInTheDocument()
    expect(screen.getByText('High-level PRD')).toBeInTheDocument()
  })

  it('renders rationale for each score', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Clear market need, validated with 50+ teams')).toBeInTheDocument()
    expect(screen.getByText('Moderate complexity due to sync logic')).toBeInTheDocument()
    expect(screen.getByText('Low barrier to entry from incumbents')).toBeInTheDocument()
    expect(screen.getByText('Strong product-market fit in remote-first companies')).toBeInTheDocument()
  })

  it('renders target users when present', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Project managers')).toBeInTheDocument()
    expect(screen.getByText('Remote teams')).toBeInTheDocument()
  })

  it('renders workflows when present', () => {
    render(<ReportCard report={completeReportFixture} />)

    expect(screen.getByText('Daily standup')).toBeInTheDocument()
    expect(screen.getByText('Async updates')).toBeInTheDocument()
  })

  it('renders the title when supplied', () => {
    render(<ReportCard report={completeReportFixture} title="My Awesome Idea" />)

    expect(screen.getByText('My Awesome Idea')).toBeInTheDocument()
  })

  it('does not render extra content when title is absent', () => {
    render(<ReportCard report={completeReportFixture} />)

    // The report should render normally
    expect(screen.getByText('Viability scorecard')).toBeInTheDocument()
    // But there should be no title header (just check we're not rendering an extra element)
    const titleElements = screen.queryAllByText(/My Awesome Idea/)
    expect(titleElements).toHaveLength(0)
  })

  it('renders the title BEFORE the "Viability scorecard" heading in document order', () => {
    const { container } = render(<ReportCard report={completeReportFixture} title="Report Title" />)

    // Get the positions in the DOM
    const titlePos = container.innerHTML.indexOf('Report Title')
    const headingPos = container.innerHTML.indexOf('Viability scorecard')

    expect(titlePos).toBeGreaterThan(-1) // Title is in the document
    expect(headingPos).toBeGreaterThan(-1) // Heading is in the document
    expect(titlePos).toBeLessThan(headingPos) // Title comes before heading
  })
})
