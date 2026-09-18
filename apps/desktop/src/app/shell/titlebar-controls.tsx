import { compactNumber } from '@hermes/shared'
import { useStore } from '@nanostores/react'
import { type ComponentProps, type MouseEvent, type ReactNode, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { hudTargetSessionId } from '@/app/hud/handoff'
import { toggleLayoutEditMode } from '@/components/pane-shell/edit-mode'
import { resetLayoutTree } from '@/components/pane-shell/tree/store'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Tip, TipKeybindLabel } from '@/components/ui/tooltip'
import { Slot } from '@/contrib/react/slot'
import { useContributions } from '@/contrib/react/use-contributions'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { formatModifierToken } from '@/lib/keybinds/combo'
import { cn } from '@/lib/utils'
import { openCommandPalette } from '@/store/command-palette'
import { toggleHud } from '@/store/hud'
import {
  $fileBrowserOpen,
  $panesFlipped,
  $sidebarOpen,
  toggleFileBrowserOpen,
  togglePanesFlipped,
  toggleSidebarOpen
} from '@/store/layout'
import { $unreadSessionCount } from '@/store/session-dot-state'
import { $titlebarAppActionsSide } from '@/store/titlebar-app-actions'

import { appViewForPath, hidesFixedTitlebarClusters, isOverlayView } from '../routes'

import {
  TITLEBAR_ICON_BADGE_SCALE,
  titlebarButtonClass,
  titlebarIconSizeCss,
  titlebarToolClusterClass
} from './titlebar'
import { TitlebarIcon } from './titlebar-icon'

export interface TitlebarTool {
  id: string
  label: string
  active?: boolean
  className?: string
  disabled?: boolean
  hidden?: boolean
  href?: string
  icon: ReactNode
  onSelect?: (event?: MouseEvent) => void
  /** Keybind action id — when set, the tooltip shows the label + keybind hint. */
  actionId?: string
  /** Overlay count on the glyph (unread sessions). Hidden when 0/undefined. */
  badge?: number
  title?: string
  to?: string
  /** Durable `data-tour` handle. Tools are addressed by icon and translated
   *  label otherwise, and neither survives a theme or a locale change. */
  tour?: string
}

export type TitlebarToolSide = 'left' | 'right'
export type SetTitlebarToolGroup = (id: string, tools: readonly TitlebarTool[], side?: TitlebarToolSide) => void

interface TitlebarControlsProps extends ComponentProps<'div'> {
  leftTools?: readonly TitlebarTool[]
  tools?: readonly TitlebarTool[]
  onOpenSettings: () => void
}

/**
 * The layout button's glyph. Morphs into its composite reset form — the
 * layout icon wearing a small counter-clockwise arrow badge ("layout, back
 * to how it was") — ONLY while the pointer is on the button AND ⌘/Ctrl is
 * held: hover gates via CSS (`group/tool` on the button), the modifier via
 * the window listener. Pressing the modifier elsewhere changes nothing.
 */
function LayoutGlyph({ modHeld }: { modHeld: boolean }) {
  return (
    <>
      <span className={cn('inline-flex', modHeld && 'group-hover/tool:hidden')}>
        <TitlebarIcon name="layout" />
      </span>
      <span className={cn('relative hidden', modHeld && 'group-hover/tool:inline-flex')}>
        <TitlebarIcon name="layout" />
        <span className="absolute -bottom-1 -right-1.5 grid place-items-center rounded-full bg-(--ui-bg-chrome) p-px">
          <TitlebarIcon className="-scale-x-100" name="refresh" size={titlebarIconSizeCss(TITLEBAR_ICON_BADGE_SCALE)} />
        </span>
      </span>
    </>
  )
}

/** Overlay count on a titlebar glyph. Hidden when count is 0/undefined. */
function withCountBadge(icon: ReactNode, count: number | undefined): ReactNode {
  if (!count) {
    return icon
  }

  return (
    <span className="relative inline-flex">
      {icon}
      <span className="pointer-events-none absolute -top-2.5 -right-1.5 z-1">
        <Badge aria-hidden size="overlay" variant="solid">
          {compactNumber(count)}
        </Badge>
      </span>
    </span>
  )
}

/** Live ⌘/Ctrl tracking — mod-click affordances telegraph themselves (the
 *  layout button morphs into its reset form while the modifier is down). */
function useModifierHeld(): boolean {
  const [held, setHeld] = useState(false)

  useEffect(() => {
    const sync = (event: KeyboardEvent) => setHeld(event.metaKey || event.ctrlKey)
    const clear = () => setHeld(false)

    window.addEventListener('keydown', sync)
    window.addEventListener('keyup', sync)
    window.addEventListener('blur', clear)

    return () => {
      window.removeEventListener('keydown', sync)
      window.removeEventListener('keyup', sync)
      window.removeEventListener('blur', clear)
    }
  }, [])

  return held
}

export function TitlebarControls({ leftTools = [], tools = [], onOpenSettings }: TitlebarControlsProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const modHeld = useModifierHeld()
  const fileBrowserOpen = useStore($fileBrowserOpen)
  const panesFlipped = useStore($panesFlipped)
  const sidebarOpen = useStore($sidebarOpen)
  const unreadCount = useStore($unreadSessionCount)
  const appActionsSide = useStore($titlebarAppActionsSide)
  const unreadBadge = unreadCount > 0 ? unreadCount : undefined
  const unreadHint = unreadBadge ? ` · ${t.titlebar.unreadSessions(unreadBadge)}` : ''

  // `titleBar.*` slot content is mount-scoped — a page's <Contribute> registers
  // only while that surface is up — so a non-empty area means a page is
  // actively projecting chrome into the band right now.
  const titleBarLeft = useContributions('titleBar.left')
  const titleBarCenter = useContributions('titleBar.center')
  const titleBarRight = useContributions('titleBar.right')
  const pageOwnsTitlebar = titleBarLeft.length + titleBarCenter.length + titleBarRight.length > 0

  // POSITIONAL toggles: each button shows/hides everything on its physical
  // side of the main zone (the layout tree collapses the whole side), so they
  // stay correct through flips and rearranges. $sidebarOpen ≙ left side,
  // $fileBrowserOpen ≙ right side. Never an active highlight — plain
  // show/hide affordances.
  const leftEdge = { open: sidebarOpen, toggle: toggleSidebarOpen }
  const rightEdge = { open: fileBrowserOpen, toggle: toggleFileBrowserOpen }
  const leftLabel = leftEdge.open ? t.titlebar.hideSidebar : t.titlebar.showSidebar
  const rightLabel = rightEdge.open ? t.titlebar.hideRightSidebar : t.titlebar.showRightSidebar

  const sidebarTool: TitlebarTool = {
    actionId: 'view.toggleSidebar',
    badge: panesFlipped ? undefined : unreadBadge,
    icon: <TitlebarIcon name="layout-sidebar-left" />,
    id: 'sidebar',
    label: `${leftLabel}${panesFlipped ? '' : unreadHint}`,
    onSelect: () => {
      triggerHaptic('tap')
      leftEdge.toggle()
    }
  }

  const flipTool: TitlebarTool = {
    actionId: 'view.flipPanes',
    icon: <TitlebarIcon name="arrow-swap" />,
    id: 'flip-panes',
    label: t.titlebar.swapSidebarSides,
    onSelect: () => {
      triggerHaptic('tap')
      togglePanesFlipped()
    }
  }

  const rightSidebarTool: TitlebarTool = {
    actionId: 'view.toggleRightSidebar',
    badge: panesFlipped ? unreadBadge : undefined,
    icon: <TitlebarIcon name="layout-sidebar-right" />,
    id: 'right-sidebar',
    label: `${rightLabel}${panesFlipped ? unreadHint : ''}`,
    onSelect: () => {
      triggerHaptic('tap')
      rightEdge.toggle()
    },
    tour: 'right-pane-toggle'
  }

  // Static system tools — always pinned to the screen's right edge so the
  // left titlebar stays free for tabs (#107351).
  const systemTools: TitlebarTool[] = [
    {
      actionId: 'nav.settings',
      icon: <TitlebarIcon name="settings-gear" />,
      id: 'settings',
      label: t.titlebar.openSettings,
      onSelect: () => {
        triggerHaptic('open')
        onOpenSettings()
      }
    },
    {
      className: 'group/tool',
      // Hover + held ⌘/Ctrl morphs the glyph into its reset form (see
      // LayoutGlyph) — the mod-click telegraphs itself before it happens.
      icon: <LayoutGlyph modHeld={modHeld} />,
      id: 'layout',
      label: t.titlebar.layoutEditor,
      onSelect: event => {
        if (event?.metaKey || event?.ctrlKey) {
          triggerHaptic('warning')
          resetLayoutTree()

          return
        }

        triggerHaptic('open')
        toggleLayoutEditMode()
      },
      title: t.titlebar.layoutEditorTitle(formatModifierToken('mod'))
    },
    {
      // No `title`: TitlebarToolButton passes `title` to TipKeybindLabel as a
      // text OVERRIDE, so a long sentence there replaces the short label and
      // crowds the ⌘⇧H hint off the tooltip. Label only — the hint is appended
      // from the action registry, same as every other tool here.
      actionId: 'view.toggleHud',
      icon: <TitlebarIcon name="comment-discussion" />,
      id: 'hud',
      label: t.titlebar.enterHud,
      onSelect: () => {
        triggerHaptic('open')
        toggleHud(hudTargetSessionId())
      }
    }
  ]

  const view = appViewForPath(location.pathname)

  // Overlays own the window. These clusters are `fixed` at a higher z-index
  // than the overlay card, so they'd otherwise bleed over it — hide them (and
  // the nested titleBar slots) and let the overlay's own chrome take over.
  if (isOverlayView(view)) {
    return null
  }

  const titlebarSlots = (
    <>
      <Slot area="titleBar.left" />
      <Slot area="titleBar.center" />
      <Slot area="titleBar.right" />
    </>
  )

  const leftClusterClass = cn(
    titlebarToolClusterClass,
    'left-(--titlebar-controls-left) top-(--titlebar-controls-top) translate-y-(--titlebar-controls-y-nudge)'
  )

  // A contributed full page (`extension`) yields the fixed clusters only while
  // it actually projects chrome into the band — page-mounted `titleBar.*` slots
  // like kanban's board switcher. A page that mounts no titlebar chrome keeps
  // the app's controls; an empty claim would leave a bare strip on every plugin
  // route. Contributed `titleBar.tools` items keep rendering here too, so a
  // chrome-owning page never silently drops a registered item.
  if (hidesFixedTitlebarClusters(view) && pageOwnsTitlebar) {
    const pageTools = [...leftTools, ...tools].filter(tool => !tool.hidden)

    return (
      <div className={leftClusterClass}>
        {pageTools.map(tool => (
          <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
        ))}
        {titlebarSlots}
      </div>
    )
  }

  const visibleLeftTools = (
    appActionsSide === 'left' ? [sidebarTool, ...systemTools, ...leftTools] : [sidebarTool, ...leftTools]
  ).filter(tool => !tool.hidden)

  const visibleSystemTools = appActionsSide === 'right' ? systemTools.filter(tool => !tool.hidden) : []
  const visiblePaneTools = tools.filter(tool => !tool.hidden)

  return (
    <header
      className="fixed top-0 inset-x-0 h-9 z-50 flex items-center justify-between border-b border-white/[0.06] bg-[#07080a]/90 backdrop-blur-xl px-3 select-none [-webkit-app-region:drag]"
      style={{
        paddingLeft: 'max(0.75rem, var(--titlebar-content-inset, 0rem))',
        paddingRight: 'var(--titlebar-tools-right, 140px)'
      }}
    >
      {/* Left: Brand + Left Tools */}
      <div aria-label={t.shell.windowControls} className="flex items-center gap-2.5 [-webkit-app-region:no-drag]" data-titlebar-cluster="left">
        <div className="flex items-center gap-1.5 mr-1.5 pointer-events-auto">
          <div className="flex size-4.5 items-center justify-center rounded-md bg-[#7170ff] text-white text-[9px] font-bold shadow-[0_0_8px_rgba(113,112,255,0.4)]">
            ✦
          </div>
          <span className="text-[11px] font-bold tracking-wider text-white">
            STELLARIUM
          </span>
          <span className="rounded bg-[#7170ff]/10 border border-[#7170ff]/20 px-1 py-0.2 text-[8px] text-[#7170ff] font-mono uppercase">
            Studio
          </span>
        </div>

        {visibleLeftTools.map(tool => (
          <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
        ))}
        <Slot area="titleBar.left" />
        <Slot area="titleBar.center" />
      </div>

      {/* Center: Clean Omnibar Command Trigger */}
      <div className="flex flex-1 justify-center max-w-xs px-2 [-webkit-app-region:no-drag]">
        <button
          className="flex h-6.5 w-full items-center justify-between rounded-full border border-white/[0.06] bg-white/[0.03] px-2.5 text-[11px] text-[#8a8f98] transition-colors hover:border-white/[0.12] hover:bg-white/[0.06] hover:text-[#d0d6e0] cursor-pointer"
          onClick={() => openCommandPalette()}
          type="button"
        >
          <span className="flex items-center gap-1.5">
            <Codicon name="search" size="0.75rem" />
            <span className="truncate">Search or command...</span>
          </span>
          <span className="font-mono text-[9px] rounded px-1.5 py-0.2 bg-white/[0.06] border border-white/[0.08] text-[#8a8f98]">
            Ctrl K
          </span>
        </button>
      </div>

      {/* Right: Live Status & System Controls */}
      <div aria-label={t.shell.appControls} className="flex items-center gap-1.5 [-webkit-app-region:no-drag]" data-titlebar-cluster="right">
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-medium text-emerald-400 mr-1">
          <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
          Online
        </span>

        {visiblePaneTools.map(tool => (
          <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
        ))}
        {visibleSystemTools.map(tool => (
          <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
        ))}
        <TitlebarToolButton navigate={navigate} tool={flipTool} />
        <TitlebarToolButton navigate={navigate} tool={rightSidebarTool} />
        <Slot area="titleBar.right" />
      </div>
    </header>
  )
}

function TitlebarToolButton({ navigate, tool }: { navigate: ReturnType<typeof useNavigate>; tool: TitlebarTool }) {
  // Titlebar actions never show an active background — state reads from the
  // icon itself (e.g. the mute/unmute glyph). aria-pressed still carries it
  // for a11y.
  const className = cn(titlebarButtonClass, 'bg-transparent select-none', tool.className)

  const tooltipLabel = tool.actionId ? (
    <TipKeybindLabel actionId={tool.actionId} text={tool.title ?? tool.label} />
  ) : (
    (tool.title ?? tool.label)
  )

  if (tool.href) {
    return (
      <Tip label={tooltipLabel}>
        <Button asChild className={className} size="icon-titlebar" variant="ghost">
          <a
            aria-label={tool.label}
            data-tour={tool.tour}
            href={tool.href}
            onPointerDown={event => event.stopPropagation()}
            rel="noreferrer"
            target="_blank"
          >
            {withCountBadge(tool.icon, tool.badge)}
          </a>
        </Button>
      </Tip>
    )
  }

  return (
    <Tip label={tooltipLabel}>
      <Button
        aria-label={tool.label}
        aria-pressed={tool.active ?? undefined}
        className={className}
        data-tour={tool.tour}
        disabled={tool.disabled}
        onClick={event => {
          if (tool.to) {
            navigate(tool.to)
          }

          tool.onSelect?.(event)
        }}
        onPointerDown={event => event.stopPropagation()}
        size="icon-titlebar"
        type="button"
        variant="ghost"
      >
        {withCountBadge(tool.icon, tool.badge)}
      </Button>
    </Tip>
  )
}
