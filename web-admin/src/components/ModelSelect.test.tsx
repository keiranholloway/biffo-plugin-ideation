import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ModelSelect, choosableModels } from './ModelSelect'
import type { ModelCatalogEntry } from '../lib/api'

/**
 * Issue #67: "the model catalog should be what models are chosen from".
 * Until this component, nothing read the catalog at all — an agent's model was
 * typed by hand, so an unservable slug (#66's `anthropic/claude-opus-4-8`) was
 * accepted silently and only failed hours later inside an async run.
 */
describe('ModelSelect', () => {
  const entries: ModelCatalogEntry[] = [
    { id: '1', model_id: 'vendor/zebra', label: 'Zebra', active: true, is_default: false },
    { id: '2', model_id: 'vendor/alpha', label: 'Alpha', active: true, is_default: false },
    { id: '3', model_id: 'vendor/def', label: 'Default one', active: true, is_default: true },
    { id: '4', model_id: 'vendor/off', label: 'Retired', active: false, is_default: false },
  ]

  describe('choosableModels', () => {
    it('offers only active entries, default first then alphabetical', () => {
      expect(choosableModels(entries).map((e) => e.model_id)).toEqual([
        'vendor/def',
        'vendor/alpha',
        'vendor/zebra',
      ])
    })

    it('does not offer a deactivated entry', () => {
      // "Active" is the admin's way of retiring a model. Offering it anyway
      // would make the toggle decorative.
      expect(choosableModels(entries).map((e) => e.model_id)).not.toContain('vendor/off')
    })
  })

  it('constrains the model to the catalog instead of accepting free text', () => {
    render(<ModelSelect entries={entries} value="" onChange={vi.fn()} />)

    const field = screen.getByLabelText('Model')
    expect(field.tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: /Default one/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Retired/ })).not.toBeInTheDocument()
  })

  it('reports the chosen model id, not its label', () => {
    const onChange = vi.fn()
    render(<ModelSelect entries={entries} value="" onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'vendor/alpha' } })

    expect(onChange).toHaveBeenCalledWith('vendor/alpha')
  })

  it('keeps an existing off-catalog model selectable rather than silently rewriting it', () => {
    // A stored agent can carry a model that has since left the catalog.
    // Dropping it from the options would make the first save of an unrelated
    // edit change the agent's model.
    render(<ModelSelect entries={entries} value="vendor/legacy" onChange={vi.fn()} />)

    const field = screen.getByLabelText('Model') as HTMLSelectElement
    expect(field.value).toBe('vendor/legacy')
    expect(screen.getByRole('option', { name: /not in the catalog/ })).toBeInTheDocument()
  })

  it('falls back to free text when the catalog is empty, and says nothing checks it', () => {
    // An empty catalog must not brick agent creation on a deployment that has
    // never seeded one.
    render(<ModelSelect entries={[]} value="" onChange={vi.fn()} />)

    expect(screen.getByLabelText('Model').tagName).toBe('INPUT')
    expect(screen.getByText(/nothing checks it/)).toBeInTheDocument()
  })

  it('offers only inactive entries as no choice at all', () => {
    render(<ModelSelect entries={[entries[3]]} value="" onChange={vi.fn()} />)

    // Not an empty dropdown that looks like a bug — the free-text fallback
    // with its explanation.
    expect(screen.getByLabelText('Model').tagName).toBe('INPUT')
  })
})
