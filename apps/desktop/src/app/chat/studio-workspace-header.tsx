import type { ReactNode } from 'react'

import { Codicon } from '@/components/ui/codicon'
import { cn } from '@/lib/utils'

export type StudioRuntimeStatus = 'offline' | 'ready' | 'working'

const STATUS_COPY: Record<StudioRuntimeStatus, { label: string; tone: string }> = {
  offline: { label: 'Offline', tone: 'bg-(--dt-destructive)' },
  ready: { label: 'Ready', tone: 'bg-(--ui-success)' },
  working: { label: 'Working', tone: 'bg-(--dt-primary-solid)' }
}

/**
 * A path is implementation detail in a chat header; the active directory's
 * basename is the useful orientation signal. Handles gateway POSIX paths and
 * local Windows paths without assuming which host owns the active session.
 */
export function workspaceLabel(cwd: null | string | undefined): string {
  const segments = cwd?.replaceAll('\\', '/').split('/').filter(Boolean)

  return segments?.at(-1) || 'Unscoped workspace'
}

interface StudioWorkspaceHeaderProps {
  children: ReactNode
  className?: string
  model: null | string
  provider: null | string
  status: StudioRuntimeStatus
  topic?: null | string
  workspace: null | string | undefined
}

/**
 * The narrow operational header for a primary Studio session. Its data comes
 * from the active runtime; it never synthesizes activity, usage, or provider
 * claims just to make the surface feel busier.
 */
export function StudioWorkspaceHeader({
  children,
  className,
  model,
  provider,
  status,
  topic,
  workspace
}: StudioWorkspaceHeaderProps) {
  const state = STATUS_COPY[status]
  const workspaceName = workspaceLabel(workspace)

  return (
    <div
      className={cn('studio-workspace-header flex min-w-0 flex-1 items-center justify-between gap-3', className)}
      data-studio-workspace-header=""
    >
      <div className="header-context flex min-w-0 flex-1 items-center gap-2.5">
        <div aria-hidden="true" className="studio-workspace-header__mark grid size-6 shrink-0 place-items-center rounded-md">
          <span className="grid grid-cols-2 gap-[2px]">
            <i className="size-[4px] rounded-[1px]" />
            <i className="size-[4px] rounded-[1px]" />
            <i className="size-[4px] rounded-[1px]" />
            <i className="size-[4px] rounded-[1px]" />
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5 text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-(--ui-text-quaternary)">
            <span>Stellarium</span>
            <Codicon aria-hidden="true" className="size-2.5 shrink-0" name="chevron-right" />
            <span className="truncate" title={workspace ?? undefined}>
              {workspaceName}
            </span>
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 text-[0.8125rem] font-medium leading-5 text-(--ui-text-primary)">{children}</div>
            {topic && (
              <div
                className="current-room-topic hidden max-w-sm truncate border-l border-(--ui-stroke-tertiary) pl-2.5 text-[0.75rem] text-(--ui-text-tertiary) xl:inline-block"
                title={topic}
              >
                {topic}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="studio-workspace-header__runtime hidden min-w-0 items-center gap-2.5 lg:flex">
        <span
          aria-label={`Agent status: ${state.label}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) px-2.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.09em] text-(--ui-text-secondary)"
        >
          <i aria-hidden="true" className={cn('size-1.5 rounded-full', state.tone)} />
          {state.label}
        </span>
        {(model || provider) && (
          <div
            className="model-status-pill flex items-center gap-1.5 rounded-full border border-(--ui-stroke-tertiary) bg-(--ui-control-active-background) px-2.5 py-0.5 text-[0.6875rem] text-(--ui-text-secondary)"
            title={[provider, model].filter(Boolean).join(' · ')}
          >
            <span className="size-1.5 rounded-full bg-(--dt-primary)" />
            <span className="max-w-44 truncate">{model}</span>
          </div>
        )}
        {provider && <span className="sr-only">{provider}</span>}
      </div>
    </div>
  )
}
