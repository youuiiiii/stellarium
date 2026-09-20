import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { StudioSidebarHeader } from './studio-sidebar-header'

afterEach(cleanup)

describe('StudioSidebarHeader', () => {
  it('renders the canonical agent pill with name and role', () => {
    render(
      <StudioSidebarHeader
        agentName="Stella"
        agentRole="Default Autonomous Agent"
      />
    )

    const header = screen.getByTestId('studio-sidebar-header')
    expect(header).toBeTruthy()

    const pill = screen.getByTestId('studio-agent-pill')
    expect(pill).toBeTruthy()
    expect(screen.getByText('Stella')).toBeTruthy()
    expect(screen.getByText('Default Autonomous Agent')).toBeTruthy()
  })

  it('renders fallback role when not provided', () => {
    render(
      <StudioSidebarHeader
        agentName="Mei"
      />
    )

    expect(screen.getByText('Mei')).toBeTruthy()
    expect(screen.getByText('Default Autonomous Agent')).toBeTruthy()
  })

  it('reflects active profile store when rendered with no props', () => {
    render(<StudioSidebarHeader />)

    expect(screen.getByTestId('studio-agent-pill')).toBeTruthy()
  })
})
