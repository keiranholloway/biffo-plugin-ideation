import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ModelCatalogList } from './ModelCatalogList'
import type { ModelCatalogEntry } from '../lib/api'

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

  it('renders a list of catalog entries', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    render(
      <ModelCatalogList
        entries={mockEntries}
        currentDefault="entry-1"
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    expect(screen.getByText('Claude 3 Sonnet')).toBeInTheDocument()
    expect(screen.getByText('Claude 3 Opus')).toBeInTheDocument()
  })

  it('shows empty state when no entries', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    render(
      <ModelCatalogList
        entries={[]}
        currentDefault={null}
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    expect(screen.getByText('No catalog entries yet.')).toBeInTheDocument()
  })

  it('shows default badge on the default entry', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    render(
      <ModelCatalogList
        entries={mockEntries}
        currentDefault="entry-1"
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    const badges = screen.getAllByText('Yes')
    expect(badges.length).toBeGreaterThan(0)
  })

  it('calls onSetDefault when "Set as Default" button is clicked', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    render(
      <ModelCatalogList
        entries={mockEntries}
        currentDefault="entry-1"
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    const setDefaultButtons = screen.getAllByText('Set as Default')
    setDefaultButtons[0].click()

    expect(onSetDefault).toHaveBeenCalledWith('entry-2', 'entry-1')
  })

  it('does not show "Set as Default" button for the current default', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    render(
      <ModelCatalogList
        entries={mockEntries}
        currentDefault="entry-1"
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    const setDefaultButtons = screen.getAllByText('Set as Default')
    expect(setDefaultButtons.length).toBe(1) // Only for the non-default entry
  })

  it('calls onDelete when delete button is clicked', () => {
    const onSetDefault = vi.fn()
    const onDelete = vi.fn()

    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(
      <ModelCatalogList
        entries={mockEntries}
        currentDefault="entry-1"
        onSetDefault={onSetDefault}
        onDelete={onDelete}
      />,
    )

    const deleteButtons = screen.getAllByText('Delete')
    deleteButtons[0].click()

    expect(onDelete).toHaveBeenCalledWith('entry-1')
  })
})
