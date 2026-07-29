import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ModelCatalogList } from './ModelCatalogList'
import type { EffectiveModel, ModelCatalogEntry } from '../lib/api'

describe('ModelCatalogList', () => {
  const mockEntries: ModelCatalogEntry[] = [
    {
      id: 'entry-1',
      model_id: 'claude-3-sonnet',
      label: 'Claude 3 Sonnet',
      active: true,
      is_default: true,
    },
    {
      id: 'entry-2',
      model_id: 'claude-3-opus',
      label: 'Claude 3 Opus',
      active: true,
      is_default: false,
    },
  ]

  const mockEffective: EffectiveModel[] = [
    {
      purpose: 'chat',
      label: 'Challenger (requirement-gathering chat)',
      model_id: 'vendor/stored-chat',
      source: 'stored',
      agent_key: 'ideation-challenger',
      env_var: 'IDEATION_CHAT_MODEL',
      env_var_is_runtime_fallback: false,
      builtin_model_id: 'anthropic/claude-sonnet-4',
      detail: 'From the stored ideation-challenger row, which is the only source.',
    },
    {
      purpose: 'analysis',
      label: 'Analyst (PRD + viability scorecard)',
      model_id: 'vendor/analysis-x',
      source: 'env',
      agent_key: 'ideation-analyst',
      env_var: 'IDEATION_ANALYSIS_MODEL',
      env_var_is_runtime_fallback: true,
      builtin_model_id: 'vendor/analysis-x',
      detail: 'No stored active analyst row, so finalise() falls back to this value.',
    },
  ]

  function noopProps() {
    return { onSetDefault: vi.fn(), onDelete: vi.fn() }
  }

  it('renders a list of catalog entries', () => {
    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={[]}
        currentDefault="entry-1"
        {...noopProps()}
      />,
    )

    expect(screen.getByText('Claude 3 Sonnet')).toBeInTheDocument()
    expect(screen.getByText('Claude 3 Opus')).toBeInTheDocument()
  })

  it('shows default badge on the default entry', () => {
    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={[]}
        currentDefault="entry-1"
        {...noopProps()}
      />,
    )

    const badges = screen.getAllByText('Yes')
    expect(badges.length).toBeGreaterThan(0)
  })

  it('calls onSetDefault when "Set as Default" button is clicked', () => {
    const props = noopProps()

    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={[]}
        currentDefault="entry-1"
        {...props}
      />,
    )

    const setDefaultButtons = screen.getAllByText('Set as Default')
    setDefaultButtons[0].click()

    expect(props.onSetDefault).toHaveBeenCalledWith('entry-2', 'entry-1')
  })

  it('does not show "Set as Default" button for the current default', () => {
    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={[]}
        currentDefault="entry-1"
        {...noopProps()}
      />,
    )

    const setDefaultButtons = screen.getAllByText('Set as Default')
    expect(setDefaultButtons.length).toBe(1) // Only for the non-default entry
  })

  it('calls onDelete when delete button is clicked', () => {
    const props = noopProps()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={[]}
        currentDefault="entry-1"
        {...props}
      />,
    )

    const deleteButtons = screen.getAllByText('Delete')
    deleteButtons[0].click()

    expect(props.onDelete).toHaveBeenCalledWith('entry-1')
  })

  // ── issue #58: an empty catalog is not "no models" ─────────────────────────

  it('shows the models actually in use when the catalog is empty', () => {
    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={mockEffective}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    // The old copy stopped at "No catalog entries yet.", which read as "no
    // models" while these two drove every run.
    expect(screen.queryByText('No catalog entries yet.')).not.toBeInTheDocument()
    expect(screen.getByText('Models in use')).toBeInTheDocument()
    expect(screen.getByText(/vendor\/stored-chat/)).toBeInTheDocument()
    expect(screen.getAllByText(/vendor\/analysis-x/).length).toBeGreaterThan(0)
  })

  // ── issue #67: the panel must not claim a model nothing is running on ──────

  it('shows a stored row as the source, not the built-in it overrides', () => {
    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={mockEffective}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    expect(screen.getByText('from its stored agent row')).toBeInTheDocument()
    // The built-in it replaced is still visible, but as the seed value it is —
    // not as "the model in use".
    expect(screen.getByText('anthropic/claude-sonnet-4')).toBeInTheDocument()
    expect(screen.getByText(/never sent to Core/)).toBeInTheDocument()
    expect(screen.queryByText(/built-in default — not stored/)).not.toBeInTheDocument()
  })

  it('renders an unconfigured chat model as a failure, not as a default', () => {
    // With chat_agents_dynamic on, no stored challenger row means Core has
    // nothing to resolve and every turn 404s. The old panel would have shown a
    // plausible model id here.
    const unconfigured: EffectiveModel[] = [
      { ...mockEffective[0], model_id: null, source: 'unconfigured' },
    ]

    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={unconfigured}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    expect(screen.getByText('not configured — this path fails')).toBeInTheDocument()
    expect(screen.queryByText(/vendor\/stored-chat/)).not.toBeInTheDocument()
  })

  it('says so when the stored rows could not be read at all', () => {
    // "We could not look" is a different claim from "nothing is stored", and
    // rendering the second for the first would report a broken deployment
    // every time Core cold-started.
    const unknown: EffectiveModel[] = [
      { ...mockEffective[0], model_id: null, source: 'unknown' },
    ]

    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={unknown}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    expect(screen.getByText(/could not read the stored rows/)).toBeInTheDocument()
  })

  it('renders the server-side explanation rather than wording of its own', () => {
    // The resolution rule and its wording live together in effective_config.py,
    // so the panel cannot describe a source the resolver does not implement.
    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={mockEffective}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    expect(screen.getByText(mockEffective[0].detail)).toBeInTheDocument()
    expect(screen.getByText(mockEffective[1].detail)).toBeInTheDocument()
  })

  it('keeps showing the models in use alongside a populated catalog', () => {
    render(
      <ModelCatalogList
        entries={mockEntries}
        effectiveModels={mockEffective}
        currentDefault="entry-1"
        {...noopProps()}
      />,
    )

    expect(screen.getByText('Models in use')).toBeInTheDocument()
    expect(screen.getByText('Claude 3 Sonnet')).toBeInTheDocument()
  })
})
