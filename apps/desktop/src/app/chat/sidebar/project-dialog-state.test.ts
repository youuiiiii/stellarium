import { describe, expect, it } from 'vitest'

import { deriveProjectDialogStudioState } from './project-dialog-state'

describe('deriveProjectDialogStudioState', () => {
  it('keeps incomplete creation quietly non-inviting until a name and folder exist', () => {
    expect(deriveProjectDialogStudioState({ folders: [], mode: 'create', name: 'Stella', submitting: false })).toBe('incomplete')
  })

  it('marks a configured create or rename flow ready', () => {
    expect(deriveProjectDialogStudioState({ folders: ['D:/work'], mode: 'create', name: 'Stella', submitting: false })).toBe('ready')
    expect(deriveProjectDialogStudioState({ folders: [], mode: 'rename', name: 'Stella', submitting: false })).toBe('ready')
  })

  it('makes an in-flight write take precedence over form readiness', () => {
    expect(deriveProjectDialogStudioState({ folders: ['D:/work'], mode: 'create', name: 'Stella', submitting: true })).toBe('working')
  })
})
