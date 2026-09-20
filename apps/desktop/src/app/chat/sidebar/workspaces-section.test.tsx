import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $activeRoomId, $workspacesConfig } from '@/store/workspaces'

import { WorkspacesSection } from './workspaces-section'

afterEach(cleanup)

describe('WorkspacesSection', () => {
  it('renders workspace rooms with clear active state and handles selection', () => {
    $workspacesConfig.set({
      version: 1,
      title: 'WORKSPACES',
      categories: [
        {
          id: 'workspace',
          name: 'Workspace',
          rooms: [
            { id: 'general', name: 'general-chat', icon: 'comment-discussion', topic: 'General assistance' },
            { id: 'coding', name: 'coding-studio', icon: 'terminal', topic: 'Software engineering' }
          ]
        }
      ]
    })
    $activeRoomId.set('general')

    const onRoomSelect = vi.fn()
    render(<WorkspacesSection onRoomSelect={onRoomSelect} />)

    expect(screen.getByTestId('studio-workspaces')).toBeTruthy()
    const generalBtn = screen.getByRole('button', { name: /general-chat/i })
    expect(generalBtn.getAttribute('aria-pressed')).toBe('true')

    const codingBtn = screen.getByRole('button', { name: /coding-studio/i })
    expect(codingBtn.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(codingBtn)
    expect(onRoomSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'coding', name: 'coding-studio' }))
    expect($activeRoomId.get()).toBe('coding')
  })

  it('renders add workspace action button when onAddWorkspace is provided', () => {
    const onAddWorkspace = vi.fn()
    render(<WorkspacesSection onAddWorkspace={onAddWorkspace} />)

    const addBtn = screen.getByRole('button', { name: 'Add workspace' })
    expect(addBtn).toBeTruthy()
    fireEvent.click(addBtn)
    expect(onAddWorkspace).toHaveBeenCalledTimes(1)
  })
})
