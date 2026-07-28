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
      model_id: 'anthropic/claude-sonnet-4',
      source: 'built-in',
      env_var: 'IDEATION_CHAT_MODEL',
    },
    {
      purpose: 'analysis',
      label: 'Analyst (PRD + viability scorecard)',
      model_id: 'vendor/analysis-x',
      source: 'env',
      env_var: 'IDEATION_ANALYSIS_MODEL',
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
    expect(screen.getByText(/anthropic\/claude-sonnet-4/)).toBeInTheDocument()
    expect(screen.getByText(/vendor\/analysis-x/)).toBeInTheDocument()
  })

  it('says of each model whether it is a built-in default or an env override', () => {
    render(
      <ModelCatalogList
        entries={[]}
        effectiveModels={mockEffective}
        currentDefault={null}
        {...noopProps()}
      />,
    )

    expect(screen.getByText(/built-in default — not stored/)).toBeInTheDocument()
    expect(screen.getByText('from IDEATION_ANALYSIS_MODEL')).toBeInTheDocument()
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
