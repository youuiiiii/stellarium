import { describe, expect, it } from 'vitest'

import { composerStudioState } from './studio-state'

describe('composerStudioState', () => {
  it('prioritizes a real active run over the disabled input state', () => {
    expect(composerStudioState({ busy: true, disabled: true })).toBe('working')
  })

  it('distinguishes an unavailable composer from a ready composer', () => {
    expect(composerStudioState({ busy: false, disabled: true })).toBe('unavailable')
    expect(composerStudioState({ busy: false, disabled: false })).toBe('ready')
  })
})
