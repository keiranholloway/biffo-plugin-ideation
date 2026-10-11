import { useState } from 'react'

interface ConfirmActionProps {
  /** Label of the button that starts the action. */
  label: string
  /** The question shown in-page before anything is changed. */
  prompt: string
  /** Label of the confirming button; defaults to `label`. */
  confirmLabel?: string
  /** `delete` renders the kit's outline destructive button, `secondary` the plain one. */
  tone?: 'delete' | 'secondary'
  onConfirm: () => void
}

/**
 * In-page replacement for `window.confirm`: the first click swaps the button
 * for the kit's `.biffo-confirm` row, and only the second click acts.
 */
export function ConfirmAction({
  label,
  prompt,
  confirmLabel,
  tone = 'delete',
  onConfirm,
}: ConfirmActionProps) {
  const [asking, setAsking] = useState(false)

  if (!asking) {
    return (
      <button
        type="button"
        className={tone === 'delete' ? 'biffo-btn-delete' : 'biffo-confirm__no'}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    )
  }

  return (
    <span className="biffo-confirm" role="group" aria-label={prompt}>
      <span className="biffo-confirm__prompt">{prompt}</span>
      <button
        type="button"
        className="biffo-btn-delete biffo-confirm__yes"
        onClick={() => {
          setAsking(false)
          onConfirm()
        }}
      >
        {confirmLabel ?? label}
      </button>
      <button type="button" className="biffo-confirm__no" onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
  )
}
