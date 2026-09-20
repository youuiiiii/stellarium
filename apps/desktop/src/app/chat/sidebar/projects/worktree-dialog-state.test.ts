import { describe, expect, it } from 'vitest'

import { deriveWorktreeDialogStudioState } from './worktree-dialog-state'

describe('deriveWorktreeDialogStudioState', () => {
  it('holds an incomplete branch form neutral until both a repository and branch exist', () => {
    expect(deriveWorktreeDialogStudioState({ convertMode: false, name: 'feature/stella', pending: false, repoPath: '' })).toBe('incomplete')
  })

  it('marks an executable branch or conversion path ready', () => {
    expect(deriveWorktreeDialogStudioState({ convertMode: false, name: 'feature/stella', pending: false, repoPath: 'D:/repo' })).toBe('ready')
    expect(deriveWorktreeDialogStudioState({ convertMode: true, name: '', pending: false, repoPath: 'D:/repo' })).toBe('ready')
  })

  it('prioritizes a real repository write over readiness', () => {
    expect(deriveWorktreeDialogStudioState({ convertMode: false, name: 'feature/stella', pending: true, repoPath: 'D:/repo' })).toBe('working')
  })
})
