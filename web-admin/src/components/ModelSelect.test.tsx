import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ModelSelect, choosableModels, roleRequiresWebSearch } from './ModelSelect'
import type { ModelCatalogEntry } from '../lib/api'

/**
 * Issue #67: "the model catalog should be what models are chosen from".
 * Until this component, nothing read the catalog at all — an agent's model was
 * typed by hand, so an unservable slug (#66's `anthropic/claude-opus-4-8`) was
 * accepted silently and only failed hours later inside an async run.
 */
describe('ModelSelect', () => {
  const entries: ModelCatalogEntry[] = [
    {
      id: '1',
      model_id: 'vendor/zebra',
      label: 'Zebra',
      active: true,
      is_default: false,
      web_capable: false,
    },
    {
      id: '2',
      model_id: 'vendor/alpha',
      label: 'Alpha',
      active: true,
      is_default: false,
      web_capable: false,
    },
    {
      id: '3',
      model_id: 'vendor/def',
      label: 'Default one',
      active: true,
      is_default: true,
      web_capable: false,
    },
    {
      id: '4',
      model_id: 'vendor/off',
      label: 'Retired',
      active: false,
      is_default: false,
      web_capable: false,
    },
  ]

  // One web-capable entry, so filtering tests have something real to narrow
  // down to rather than exercising the "nothing is web-capable" fallback.
  const entriesWithWebCapable: ModelCatalogEntry[] = [
    ...entries,
    {
      id: '5',
      model_id: 'vendor/alpha:online',
      label: 'Alpha (web)',
      active: true,
      is_default: false,
      web_capable: true,
    },
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

  // ── issue #92: web capability ────────────────────────────────────────────

  describe('roleRequiresWebSearch', () => {
    it('is true only for the analyst role', () => {
      expect(roleRequiresWebSearch('analyst')).toBe(true)
    })

    it('is false for the challenger role, other roles, and no role at all', () => {
      expect(roleRequiresWebSearch('challenger')).toBe(false)
      expect(roleRequiresWebSearch('reviewer')).toBe(false)
      expect(roleRequiresWebSearch(undefined)).toBe(false)
    })
  })

  describe('choosableModels with requireWebCapable', () => {
    it('narrows to active, web-capable entries only', () => {
      expect(
        choosableModels(entriesWithWebCapable, { requireWebCapable: true }).map((e) => e.model_id),
      ).toEqual(['vendor/alpha:online'])
    })

    it('is a no-op when requireWebCapable is not set', () => {
      expect(choosableModels(entriesWithWebCapable).length).toBe(
        choosableModels(entriesWithWebCapable, { requireWebCapable: false }).length,
      )
    })
  })

  it('filters to web-capable models for a role that requires search', () => {
    render(
      <ModelSelect entries={entriesWithWebCapable} value="" onChange={vi.fn()} role="analyst" />,
    )

    expect(screen.getByRole('option', { name: /Alpha \(web\)/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /^Zebra/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /^Alpha \(vendor\/alpha\)/ })).not.toBeInTheDocument()
    expect(screen.getByText(/only web-capable/)).toBeInTheDocument()
  })

  it('does not filter for a role that does not require search', () => {
    render(
      <ModelSelect entries={entriesWithWebCapable} value="" onChange={vi.fn()} role="challenger" />,
    )

    expect(screen.getByRole('option', { name: /^Zebra/ })).toBeInTheDocument()
    expect(screen.queryByText(/only web-capable/)).not.toBeInTheDocument()
  })

  it('flags a stored selection that is not web-capable rather than silently rewriting it', () => {
    // Same shape as the existing off-catalog case: the model is real and in
    // the catalog, it just cannot search — filtering it out of the options
    // must not filter it out of the *value*.
    render(
      <ModelSelect
        entries={entriesWithWebCapable}
        value="vendor/alpha"
        onChange={vi.fn()}
        role="analyst"
      />,
    )

    const field = screen.getByLabelText('Model') as HTMLSelectElement
    expect(field.value).toBe('vendor/alpha')
    expect(
      screen.getByRole('option', { name: /not web-capable, but this role requires search/ }),
    ).toBeInTheDocument()
  })

  it('falls back to every active model with a warning when none is web-capable yet', () => {
    // entries (no ':online' sibling) has zero web-capable rows — filtering to
    // nothing would strand the admin with an empty picker.
    render(<ModelSelect entries={entries} value="" onChange={vi.fn()} role="analyst" />)

    const field = screen.getByLabelText('Model')
    expect(field.tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: /^Zebra/ })).toBeInTheDocument()
    expect(screen.getByText(/no catalog entry is marked web-capable yet/)).toBeInTheDocument()
  })
})
