export type ProjectDialogStudioState = 'incomplete' | 'ready' | 'working'

export function deriveProjectDialogStudioState({
  folders,
  mode,
  name,
  submitting
}: {
  folders: string[]
  mode: 'add-folder' | 'create' | 'rename'
  name: string
  submitting: boolean
}): ProjectDialogStudioState {
  if (submitting) {
    return 'working'
  }

  if (mode === 'add-folder' || (name.trim() && (mode === 'rename' || folders.length > 0))) {
    return 'ready'
  }

  return 'incomplete'
}
