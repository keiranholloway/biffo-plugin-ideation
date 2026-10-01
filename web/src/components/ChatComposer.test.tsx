import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ChatComposer } from './ChatComposer'

function setup(over: Partial<{ value: string; busy: boolean; capped: boolean }> = {}) {
  const onSend = vi.fn()
  render(
    <ChatComposer label="Msg" value="hello" onChange={() => {}} onSend={onSend} busy={false} capped={false} {...over} />,
  )
  return { onSend, box: screen.getByLabelText('Msg') }
}

describe('ChatComposer', () => {
  it('is a multi-line textarea', () => {
    expect(setup().box.tagName).toBe('TEXTAREA')
  })
  it('Enter does not send', () => {
    const { onSend, box } = setup()
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
  })
  it('Ctrl+Enter and Cmd+Enter send', () => {
    const { onSend, box } = setup()
    fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true })
    fireEvent.keyDown(box, { key: 'Enter', metaKey: true })
    expect(onSend).toHaveBeenCalledTimes(2)
  })
  it('cannot send empty or whitespace', () => {
    const { onSend, box } = setup({ value: '  \n ' })
    fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true })
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
  it('disables at the turn cap and when busy', () => {
    setup({ capped: true })
    expect(screen.getByLabelText('Msg')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})
