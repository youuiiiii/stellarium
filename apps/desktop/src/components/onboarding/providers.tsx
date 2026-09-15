import { useEffect, useState } from 'react'
import { RowButton } from '@/components/ui/row-button'
import { useI18n } from '@/i18n'
import { Check, ChevronRight, Terminal } from '@/lib/icons'
import { cn } from '@/lib/utils'
import type { OAuthProvider } from '@/types/hermes'

const PROVIDER_DISPLAY: Record<string, { order: number; title: string }> = {
  nous: { order: 0, title: 'Nous Portal' },
  'openai-codex': { order: 1, title: 'ChatGPT or Codex Subscription' },
  'minimax-oauth': { order: 2, title: 'MiniMax' },
  'qwen-oauth': { order: 3, title: 'Qwen Code' },
  'xai-oauth': { order: 4, title: 'xAI Grok' },
  // Both Anthropic entries sit at the bottom: the API-key path first, then
  // the subscription OAuth path (only works with extra usage credits).
  anthropic: { order: 5, title: 'Anthropic API Key' },
  'claude-code': { order: 6, title: 'Anthropic OAuth: Required Extra Usage Credits to Use Subscription' }
}

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

export const providerTitle = (p: OAuthProvider) => PROVIDER_DISPLAY[p.id]?.title ?? p.name
const orderOf = (p: OAuthProvider) => PROVIDER_DISPLAY[p.id]?.order ?? 99

export const sortProviders = (providers: OAuthProvider[]) =>
  [...providers].sort((a, b) => orderOf(a) - orderOf(b) || a.name.localeCompare(b.name))

export function FeaturedProviderRow({
  onSelect,
  provider
}: {
  onSelect: (provider: OAuthProvider) => void
  provider: OAuthProvider
}) {
  const { t } = useI18n()
  const freeTier = provider.status?.free_tier === true
  const loggedIn = provider.status?.logged_in && !freeTier

  return (
    <button
      className="group relative flex w-full items-center justify-between gap-4 rounded-[8px] bg-primary/[0.06] px-3 py-2.5 text-left transition-colors hover:bg-primary/10"
      onClick={() => onSelect(provider)}
      type="button"
    >
      <span aria-hidden className="arc-border arc-reverse arc-nous" />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <img alt="" className="size-5 shrink-0 rounded" src={assetPath('apple-touch-icon.png')} />
          <span className="text-[length:var(--conversation-text-font-size)] font-semibold">
            {freeTier ? t.freeTier.providerRowTitle : providerTitle(provider)}
          </span>
          {freeTier ? (
            <FreeTierTag />
          ) : loggedIn ? (
            <ConnectedTag />
          ) : (
            <span className="inline-flex items-center gap-1.5 bg-primary px-2 py-0.5 text-[0.64rem] font-semibold uppercase tracking-[0.16em] text-primary-foreground">
              <span aria-hidden="true" className="dither inline-block size-2 shrink-0" />
              {t.onboarding.recommended}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {freeTier ? t.freeTier.providerRowPitch : t.onboarding.featuredPitch}
        </p>
      </div>
      <ChevronRight className="size-4 shrink-0 text-primary transition group-hover:translate-x-0.5" />
    </button>
  )
}

// The free tier is an identity without an account: never "Connected", never the account's name.
function FreeTierTag() {
  const { t } = useI18n()

  return (
    <span className="inline-flex items-center gap-1 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      {t.onboarding.freeTier}
    </span>
  )
}

function ConnectedTag() {
  const { t } = useI18n()

  return (
    <span className="inline-flex items-center gap-1 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      <Check className="size-3" />
      {t.onboarding.connected}
    </span>
  )
}

const PROVIDER_ROW_CLASS =
  'group flex w-full items-center justify-between gap-3 rounded-[6px] px-3 py-2.5 text-left transition-colors hover:bg-(--ui-control-hover-background)'

/** Quick-key row for API-key providers (Fireworks leads the expanded list after Nous, OpenRouter further down). */
export function KeyProviderRow({ onClick, pitch, title }: { onClick: () => void; pitch: string; title: string }) {
  return (
    <RowButton className={PROVIDER_ROW_CLASS} onClick={onClick}>
      <div className="min-w-0">
        <span className="text-[length:var(--conversation-text-font-size)] font-semibold">{title}</span>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{pitch}</p>
      </div>
      <ChevronRight className="size-4 text-muted-foreground transition group-hover:text-foreground" />
    </RowButton>
  )
}

export function FireworksProviderRow({ onClick }: { onClick: () => void }) {
  const { t } = useI18n()

  return <KeyProviderRow onClick={onClick} pitch={t.onboarding.fireworksPitch} title="Fireworks AI" />
}

/** Onboarding row for the managed local runtime: no account, no key — the
 *  destination is the Local Models pane where install/download live. */
export function LocalModelsProviderRow({ onClick }: { onClick: () => void }) {
  const { t } = useI18n()

  return (
    <KeyProviderRow onClick={onClick} pitch={t.onboarding.localModelsPitch} title={t.onboarding.localModelsTitle} />
  )
}

/** Native Antigravity Pro (9Router) provider row */
export function AntigravityProviderRow({ onClick }: { onClick: () => void }) {
  const [alive, setAlive] = useState(false)

  useEffect(() => {
    let cancelled = false
    void window.hermesDesktop?.routerSupervisor?.isAlive().then(res => {
      if (!cancelled) setAlive(Boolean(res))
    }).catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <button
      className="group relative flex w-full items-center justify-between gap-4 rounded-[8px] border border-primary/30 bg-primary/[0.08] px-3.5 py-3 text-left transition-all hover:border-primary/60 hover:bg-primary/[0.14] shadow-[0_0_16px_rgba(157,114,255,0.12)] cursor-pointer"
      onClick={onClick}
      type="button"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-[#7c3aed] to-[#9d72ff] text-[11px] font-bold text-white shadow-[0_0_8px_rgba(157,114,255,0.5)]">
            ✦
          </span>
          <span className="text-[length:var(--conversation-text-font-size)] font-bold text-foreground">
            Antigravity Pro (9Router)
          </span>
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.65rem] font-semibold tracking-wider uppercase',
              alive
                ? 'border border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
                : 'border border-purple-500/30 bg-purple-500/15 text-purple-300'
            )}
          >
            <span className={cn('size-1.5 rounded-full', alive ? 'animate-pulse bg-emerald-400' : 'bg-purple-400')} />
            {alive ? 'Ready (port 20128)' : '1-Click Connect'}
          </span>
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Local Antigravity runner on port 20128 — Claude 3.7 Sonnet & Gemini Pro.
        </p>
      </div>
      <ChevronRight className="size-4 shrink-0 text-primary transition group-hover:translate-x-0.5" />
    </button>
  )
}

export function OpenRouterProviderRow({ onClick }: { onClick: () => void }) {
  const { t } = useI18n()

  return <KeyProviderRow onClick={onClick} pitch={t.onboarding.openRouterPitch} title="OpenRouter" />
}

export function ProviderRow({
  onSelect,
  provider
}: {
  onSelect: (provider: OAuthProvider) => void
  provider: OAuthProvider
}) {
  const { t } = useI18n()
  const freeTier = provider.status?.free_tier === true
  const loggedIn = provider.status?.logged_in && !freeTier
  const Trail = provider.flow === 'external' ? Terminal : ChevronRight

  return (
    <RowButton className={PROVIDER_ROW_CLASS} onClick={() => onSelect(provider)}>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--conversation-text-font-size)] font-semibold">
            {freeTier ? t.freeTier.providerRowTitle : providerTitle(provider)}
          </span>
          {freeTier ? <FreeTierTag /> : loggedIn ? <ConnectedTag /> : null}
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{t.onboarding.flowSubtitles[provider.flow]}</p>
      </div>
      <Trail className="size-4 text-muted-foreground transition group-hover:text-foreground" />
    </RowButton>
  )
}
