export type ComposerStudioState = 'ready' | 'unavailable' | 'working'
export type ComposerDockLayout = 'docked' | 'floating'

export interface ComposerDockStudioStateOptions {
  busy: boolean
  disabled: boolean
  poppedOut: boolean
}

export interface ComposerDockStudioState {
  layout: ComposerDockLayout
  state: ComposerStudioState
}

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

/**
 * Resolves the Studio dock layout and active runtime state for the outer
 * composer dock container.
 */
export function composerDockStudioState({
  busy,
  disabled,
  poppedOut
}: ComposerDockStudioStateOptions): ComposerDockStudioState {
  return {
    layout: poppedOut ? 'floating' : 'docked',
    state: composerStudioState({ busy, disabled })
  }
}
