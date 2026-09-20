import { describe, expect, it } from 'vitest'

import { composerDockStudioState, composerStudioState } from './studio-state'

describe('composerStudioState', () => {
  it('prioritizes a real active run over the disabled input state', () => {
    expect(composerStudioState({ busy: true, disabled: true })).toBe('working')
  })

  it('distinguishes an unavailable composer from a ready composer', () => {
    expect(composerStudioState({ busy: false, disabled: true })).toBe('unavailable')
    expect(composerStudioState({ busy: false, disabled: false })).toBe('ready')
  })
})

describe('composerDockStudioState', () => {
  it('resolves docked layout and live state', () => {
    expect(composerDockStudioState({ busy: false, disabled: false, poppedOut: false })).toEqual({
      layout: 'docked',
      state: 'ready'
    })
    expect(composerDockStudioState({ busy: true, disabled: false, poppedOut: false })).toEqual({
      layout: 'docked',
      state: 'working'
    })
  })

  it('resolves floating layout and unavailable state', () => {
    expect(composerDockStudioState({ busy: false, disabled: true, poppedOut: true })).toEqual({
      layout: 'floating',
      state: 'unavailable'
    })
  })
})
