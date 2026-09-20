export type WorktreeDialogStudioState = 'incomplete' | 'ready' | 'working'

export function deriveWorktreeDialogStudioState({
  convertMode,
  name,
  pending,
  repoPath
}: {
  convertMode: boolean
  name: string
  pending: boolean
  repoPath: string
}): WorktreeDialogStudioState {
  if (pending) {
    return 'working'
  }

  if (convertMode || (repoPath && name.trim())) {
    return 'ready'
  }

  return 'incomplete'
}
