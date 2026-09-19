import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { StudioWorkspaceHeader, workspaceLabel } from './studio-workspace-header'

afterEach(cleanup)

describe('workspaceLabel', () => {
  it.each([
    ['D:\\10_Projects\\Project_Stella\\stellarium', 'stellarium'],
    ['/workspaces/stellarium/apps/desktop', 'desktop'],
    [null, 'Unscoped workspace']
  ])('renders a concise workspace label for %s', (cwd, expected) => {
    expect(workspaceLabel(cwd)).toBe(expected)
  })
})

describe('StudioWorkspaceHeader', () => {
  it('keeps the active session, real runtime status, workspace, and model glanceable', () => {
    render(
      <StudioWorkspaceHeader
        model="gpt-5.6-terra"
        provider="Local Antigravity"
        status="working"
        workspace="D:\\10_Projects\\Project_Stella\\stellarium"
      >
        <button type="button">Rework the desktop shell</button>
      </StudioWorkspaceHeader>
    )

    expect(screen.getByText('Stellarium')).toBeTruthy()
    expect(screen.getByText('stellarium')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Rework the desktop shell' })).toBeTruthy()
    expect(screen.getByLabelText('Agent status: Working').textContent).toContain('Working')
    expect(screen.getByText('gpt-5.6-terra')).toBeTruthy()
    expect(screen.getByText('Local Antigravity')).toBeTruthy()
  })

  it('does not pretend an unavailable gateway is ready', () => {
    render(
      <StudioWorkspaceHeader model={null} provider={null} status="offline" workspace={null}>
        <span>New session</span>
      </StudioWorkspaceHeader>
    )

    expect(screen.getByLabelText('Agent status: Offline').textContent).toContain('Offline')
    expect(screen.getByText('Unscoped workspace')).toBeTruthy()
    expect(screen.queryByText('Model unavailable')).toBeNull()
  })
})
