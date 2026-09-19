export type ComposerStudioState = 'ready' | 'unavailable' | 'working'

/**
 * A compact, truthful signal for the composer dock. `busy` wins because an
 * active run can keep the input temporarily disabled while it is still the
 * most important state for a person monitoring the work.
 */
export function composerStudioState({ busy, disabled }: { busy: boolean; disabled: boolean }): ComposerStudioState {
  if (busy) {
    return 'working'
  }

  return disabled ? 'unavailable' : 'ready'
}
