import { useStore } from '@nanostores/react'
import type * as React from 'react'

import { Codicon } from '@/components/ui/codicon'
import { DisclosureCaret } from '@/components/ui/disclosure-caret'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
  $activeRoomId,
  $collapsedCategories,
  $workspacesConfig,
  selectRoom,
  toggleCategory,
  type WorkspaceCategory,
  type WorkspaceRoom
} from '@/store/workspaces'

function RoomIcon({ name }: { name?: string }) {
  const iconMap: Record<string, string> = {
    terminal: 'terminal',
    folder: 'folder',
    'split-horizontal': 'split-horizontal',
    'file-code': 'file-code',
    bell: 'bell',
    pulse: 'pulse',
    heart: 'heart',
    coffee: 'coffee',
    sparkle: 'sparkle',
    music: 'music',
    'device-tv': 'device-camera-video',
    'chart-candle': 'graph',
    'chart-line': 'graph-line',
    wallet: 'credit-card'
  }
  const codiconName = name && iconMap[name] ? iconMap[name] : 'symbol-misc'
  return <Codicon className="size-3.5 shrink-0 opacity-75 transition-opacity group-hover:opacity-100" name={codiconName} />
}

interface WorkspacesSectionProps {
  onRoomSelect?: (room: WorkspaceRoom) => void
  onNewSessionInWorkspace?: (cwd: string | null) => void
}

export function WorkspacesSection({ onRoomSelect, onNewSessionInWorkspace }: WorkspacesSectionProps) {
  const config = useStore($workspacesConfig)
  const activeRoomId = useStore($activeRoomId)
  const collapsed = useStore($collapsedCategories)

  if (!config || !config.categories || config.categories.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-2 px-1 pb-2 pt-1 font-sans text-xs">
      <div className="flex items-center justify-between px-2 pt-1 text-[0.6875rem] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">
        <span>{config.title || 'Workspaces & Rooms'}</span>
      </div>

      {config.categories.map((cat: WorkspaceCategory) => {
        const isOpen = !collapsed.has(cat.id)

        return (
          <div className="flex flex-col gap-0.5" key={cat.id}>
            <button
              className="group flex w-full items-center justify-between rounded px-2 py-1 text-left text-[0.6875rem] font-medium tracking-wide text-(--ui-text-quaternary) transition-colors hover:bg-(--ui-control-hover-background) hover:text-(--ui-text-secondary)"
              onClick={() => toggleCategory(cat.id)}
              type="button"
            >
              <span className="truncate">{cat.name}</span>
              <DisclosureCaret
                className="opacity-0 transition-opacity group-hover:opacity-100"
                open={isOpen}
                size="0.65rem"
              />
            </button>

            {isOpen && (
              <div className="flex flex-col gap-0.5 pl-1">
                {cat.rooms.map((room: WorkspaceRoom) => {
                  const isActive = activeRoomId === room.id

                  const roomButton = (
                    <button
                      className={cn(
                        'group flex h-7.5 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[0.8125rem] font-medium transition-all duration-150',
                        isActive
                          ? 'border border-primary/30 bg-primary/10 text-foreground font-semibold shadow-[0_0_12px_rgba(157,114,255,0.15)]'
                          : 'border border-transparent text-(--ui-text-secondary) hover:bg-white/[0.04] hover:text-foreground'
                      )}
                      onClick={() => {
                        selectRoom(room)
                        onRoomSelect?.(room)
                        if (room.cwd && onNewSessionInWorkspace) {
                          onNewSessionInWorkspace(room.cwd)
                        }
                      }}
                      type="button"
                    >
                      <RoomIcon name={room.icon} />
                      <span className="min-w-0 flex-1 truncate">{room.name}</span>
                      {isActive && (
                        <span className="size-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_8px_#9d72ff]" />
                      )}
                    </button>
                  )

                  if (room.topic) {
                    return (
                      <Tip key={room.id} label={room.topic} side="right">
                        {roomButton}
                      </Tip>
                    )
                  }

                  return <div key={room.id}>{roomButton}</div>
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
