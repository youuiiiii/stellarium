import { useStore } from '@nanostores/react'
import type * as React from 'react'

import { Codicon } from '@/components/ui/codicon'
import { cn } from '@/lib/utils'
import { $activeGatewayProfile, $profiles, selectProfile } from '@/store/profile'

export interface StudioSidebarHeaderProps extends React.ComponentProps<'div'> {
  agentName?: string
  agentRole?: string
  avatar?: React.ReactNode
  onClick?: () => void
}

export function StudioSidebarHeader({
  agentName,
  agentRole,
  avatar,
  className,
  onClick,
  ...props
}: StudioSidebarHeaderProps) {
  const activeProfile = useStore($activeGatewayProfile)
  const profiles = useStore($profiles)

  const currentProfileInfo = profiles.find(p => p.name === activeProfile)

  const resolvedName =
    agentName ??
    (currentProfileInfo?.display_name || (activeProfile === 'default' ? 'Stella' : activeProfile))

  const resolvedRole =
    agentRole ??
    (currentProfileInfo?.model || 'Default Autonomous Agent')

  const handleClick = () => {
    if (onClick) {
      onClick()

      return
    }

    // Default behavior: cycle through profiles if multiple exist
    if (profiles.length > 1) {
      const currentIndex = profiles.findIndex(p => p.name === activeProfile)
      const nextIndex = (currentIndex + 1) % profiles.length
      const nextProfile = profiles[nextIndex]

      if (nextProfile) {
        selectProfile(nextProfile.name)
      }
    }
  }

  return (
    <div
      className={cn('flex shrink-0 items-center justify-between pb-2 pt-1', className)}
      data-studio-sidebar-header=""
      data-testid="studio-sidebar-header"
      {...props}
    >
      <button
        className="group/agent-pill flex w-full items-center gap-2.5 rounded-xl border border-(--ui-stroke-tertiary) bg-white/[0.03] px-2.5 py-1.5 text-left transition-all hover:border-(--ui-stroke-secondary) hover:bg-white/[0.06]"
        data-studio-agent-pill=""
        data-testid="studio-agent-pill"
        onClick={handleClick}
        type="button"
      >
        <div
          aria-hidden="true"
          className="grid size-6.5 shrink-0 place-items-center rounded-full bg-linear-to-br from-indigo-500 to-purple-500 text-xs font-bold text-white shadow-xs"
        >
          {avatar ?? '🌟'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-foreground">
            {resolvedName}
          </div>
          <div className="truncate text-[0.6875rem] text-(--ui-text-tertiary)">
            {resolvedRole}
          </div>
        </div>
        <Codicon
          className="text-(--ui-text-quaternary) transition-colors group-hover/agent-pill:text-(--ui-text-secondary)"
          name="chevron-down"
          size="0.75rem"
        />
      </button>
    </div>
  )
}
