import { useStore } from '@nanostores/react'
import { type MouseEvent } from 'react'
import { useNavigate } from 'react-router'

import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { openCommandPalette } from '@/store/command-palette'
import { $sidebarOpen, toggleSidebarOpen } from '@/store/layout'
import { $sessions } from '@/store/session'
import { SETTINGS_ROUTE } from '../routes'
import { useWindowControlsOverlayWidth } from './hooks/use-window-controls-overlay-width'
import { titlebarToolsRightCss } from './titlebar'

export function StellariumTopChrome() {
  const navigate = useNavigate()
  const sidebarOpen = useStore($sidebarOpen)
  const sessions = useStore($sessions)
  const nativeOverlayWidth = useWindowControlsOverlayWidth()
  const rightInset = titlebarToolsRightCss(nativeOverlayWidth)

  return (
    <header
      className="relative z-40 flex h-11 w-full shrink-0 select-none items-center justify-between border-b border-white/[0.08] bg-[#06060c]/90 px-3 backdrop-blur-2xl [-webkit-app-region:drag]"
      data-slot="stellarium-top-chrome"
      style={{ paddingRight: `calc(0.75rem + ${rightInset})` }}
    >
      {/* Brand Cluster (Left) */}
      <div className="flex shrink-0 items-center gap-2.5 [-webkit-app-region:no-drag]">
        <div className="flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#9d72ff] via-[#8b5cf6] to-[#6d28d9] text-white shadow-[0_0_12px_rgba(157,114,255,0.4)] border border-white/[0.15]">
          <span className="text-xs font-bold">✦</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-sans text-[13px] font-bold tracking-wider text-white">
            STELLARIUM
          </span>
          <span className="rounded-full border border-[#9d72ff]/30 bg-[#9d72ff]/15 px-2 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider text-[#b794f6]">
            Sovereign Studio
          </span>
        </div>
      </div>

      {/* Omnibar / Command Search Trigger (Center) */}
      <div className="flex max-w-md flex-1 justify-center px-4">
        <button
          className="flex h-7.5 w-full max-w-sm items-center justify-between rounded-full border border-white/[0.08] bg-white/[0.04] px-3.5 text-xs text-muted-foreground transition-all hover:border-[#9d72ff]/35 hover:bg-white/[0.07] hover:text-white [-webkit-app-region:no-drag] cursor-pointer shadow-sm"
          onClick={() => openCommandPalette()}
          type="button"
        >
          <span className="flex items-center gap-2 truncate">
            <Codicon name="search" size="0.8rem" />
            <span className="truncate">Search agents, workspaces, skills, or commands...</span>
          </span>
          <kbd className="ml-2 shrink-0 rounded border border-white/10 bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-white/70">
            Ctrl K
          </kbd>
        </button>
      </div>

      {/* Status & Quick Actions (Right) */}
      <div className="flex shrink-0 items-center gap-2 [-webkit-app-region:no-drag]">
        <div className="flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-400">
          <span className="size-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse" />
          <span>Gateway Online</span>
        </div>

        <Tip label={sidebarOpen ? 'Hide Studio Dock (Ctrl+B)' : 'Show Studio Dock (Ctrl+B)'}>
          <button
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-all ${
              sidebarOpen
                ? 'border-[#9d72ff]/30 bg-[#9d72ff]/15 text-white shadow-[0_0_10px_rgba(157,114,255,0.2)]'
                : 'border-white/[0.08] bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07] hover:text-white'
            }`}
            onClick={() => toggleSidebarOpen()}
            type="button"
          >
            <Codicon name="layout-sidebar-left" size="0.85rem" />
            <span>Dock</span>
            <kbd className="ml-1 font-mono text-[9px] opacity-70">Ctrl B</kbd>
          </button>
        </Tip>

        <Tip label="Open Settings & Engine">
          <button
            className="flex size-7 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-muted-foreground transition-all hover:bg-white/[0.07] hover:text-white"
            onClick={() => navigate(SETTINGS_ROUTE)}
            type="button"
          >
            <Codicon name="settings-gear" size="0.85rem" />
          </button>
        </Tip>
      </div>
    </header>
  )
}
