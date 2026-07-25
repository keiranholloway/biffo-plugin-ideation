import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { Sidebar } from './Sidebar'
import type { SessionSummary } from '../lib/api'

describe('Sidebar', () => {
  it('renders sessions with title, date, and status', () => {
    const sessions: SessionSummary[] = [
      { session_id: 's1', title: 'First idea', status: 'complete', created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'Second idea', status: 'gathering', created_at: '2026-07-24T15:30:00Z' },
    ]
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    render(<Sidebar sessions={sessions} activeId={null} onSelect={onSelect} onNewIdea={onNewIdea} />)

    expect(screen.getByText('First idea')).toBeInTheDocument()
    expect(screen.getByText('Second idea')).toBeInTheDocument()
    expect(screen.getByText('complete')).toBeInTheDocument()
    expect(screen.getByText('gathering')).toBeInTheDocument()
  })

  it('shows empty state when there are no sessions', () => {
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    render(<Sidebar sessions={[]} activeId={null} onSelect={onSelect} onNewIdea={onNewIdea} />)

    expect(screen.getByText('No past runs yet')).toBeInTheDocument()
  })

  it('calls onSelect with the session when clicking an item', () => {
    const sessions: SessionSummary[] = [
      { session_id: 's1', title: 'My idea', status: 'complete', created_at: '2026-07-25T10:00:00Z' },
    ]
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    render(<Sidebar sessions={sessions} activeId={null} onSelect={onSelect} onNewIdea={onNewIdea} />)

    screen.getByText('My idea').click()
    expect(onSelect).toHaveBeenCalledWith(sessions[0])
  })

  it('calls onNewIdea when clicking the + New idea button', () => {
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    render(<Sidebar sessions={[]} activeId={null} onSelect={onSelect} onNewIdea={onNewIdea} />)

    screen.getByText('+ New idea').click()
    expect(onNewIdea).toHaveBeenCalled()
  })

  it('marks the active session item as active', () => {
    const sessions: SessionSummary[] = [
      { session_id: 's1', title: 'First', status: 'complete', created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'Second', status: 'gathering', created_at: '2026-07-24T15:30:00Z' },
    ]
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    const { container } = render(<Sidebar sessions={sessions} activeId="s2" onSelect={onSelect} onNewIdea={onNewIdea} />)

    const activeItem = container.querySelector('.ide-sidebar-item--active')
    expect(activeItem).toHaveTextContent('Second')
  })

  it('formats the date from created_at', () => {
    const sessions: SessionSummary[] = [
      { session_id: 's1', title: 'Test idea', status: 'complete', created_at: '2026-07-25T10:00:00Z' },
    ]
    const onSelect = vi.fn()
    const onNewIdea = vi.fn()

    render(<Sidebar sessions={sessions} activeId={null} onSelect={onSelect} onNewIdea={onNewIdea} />)

    const dateString = new Date('2026-07-25T10:00:00Z').toLocaleDateString()
    expect(screen.getByText(dateString)).toBeInTheDocument()
  })
})
