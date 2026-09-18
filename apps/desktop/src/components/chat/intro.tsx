import { useStore } from '@nanostores/react'
import { useState } from 'react'
import { useAui } from '@assistant-ui/react'

import { capitalize, normalize } from '@/lib/text'
import { $activeMascotId, $customMascotData, resolveMascotSrc } from '@/store/mascot'

import introCopyJsonl from './intro-copy.jsonl?raw'

type IntroCopy = {
  headline: string
  body: string
}

type IntroCopyRecord = IntroCopy & {
  personality: string
}

export type IntroProps = {
  personality?: string
  seed?: number
}

const NEUTRAL_PERSONALITIES = new Set(['', 'default', 'none', 'neutral'])

const FALLBACK_COPY: IntroCopy[] = [
  {
    headline: 'What are we moving today?',
    body: "Send a bug, branch, plan, or rough idea. I'll inspect the repo and turn it into the next concrete step."
  },
  {
    headline: "What's on your mind?",
    body: "Bring the code, question, or stuck part. I'll read the room before making changes."
  },
  {
    headline: 'What should Stella look at?',
    body: "Send the task, failing path, or half-formed plan. I'll help turn it into action."
  },
  {
    headline: 'Where should we start?',
    body: "Bring the problem, goal, or file. I'll inspect first and keep the next step concrete."
  },
  {
    headline: 'What needs attention?',
    body: "Send the context you have. I'll help sort it into a plan or a fix."
  }
]

function normalizeKey(value?: string): string {
  return normalize(value)
}

function titleize(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(capitalize)
    .join(' ')
}

function isIntroCopyRecord(value: unknown): value is IntroCopyRecord {
  if (!value || typeof value !== 'object') {
    return false
  }

  const record = value as Record<string, unknown>

  return (
    typeof record.personality === 'string' &&
    typeof record.headline === 'string' &&
    typeof record.body === 'string' &&
    Boolean(record.personality.trim()) &&
    Boolean(record.headline.trim()) &&
    Boolean(record.body.trim())
  )
}

function parseIntroCopy(raw: string): Record<string, IntroCopy[]> {
  const byPersonality: Record<string, IntroCopy[]> = {}

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim()

    if (!trimmed) {
      continue
    }

    try {
      const parsed: unknown = JSON.parse(trimmed)

      if (!isIntroCopyRecord(parsed)) {
        continue
      }

      const key = normalizeKey(parsed.personality)
      byPersonality[key] ??= []
      byPersonality[key].push({
        headline: parsed.headline.trim(),
        body: parsed.body.trim()
      })
    } catch {
      // Bad generated copy should not break the whole desktop app.
    }
  }

  return byPersonality
}

const INTRO_COPY_BY_PERSONALITY = parseIntroCopy(introCopyJsonl)

function neutralCopy(): IntroCopy[] {
  return INTRO_COPY_BY_PERSONALITY.none || INTRO_COPY_BY_PERSONALITY.default || FALLBACK_COPY
}

function fallbackCopyForPersonality(personalityKey: string): IntroCopy[] {
  if (NEUTRAL_PERSONALITIES.has(personalityKey)) {
    return neutralCopy()
  }

  const label = titleize(personalityKey)

  return [
    {
      headline: `${label} mode is on. What should we work on?`,
      body: "Send the task, file, or rough idea. I'll use your configured voice and keep the work grounded in this repo."
    },
    {
      headline: `What does ${label} Stella need to see?`,
      body: "Bring the context or the stuck part. I'll adapt to your configured personality."
    },
    {
      headline: `${label} mode is ready.`,
      body: "Send the problem, file, or idea. I'll follow the personality you've configured."
    },
    {
      headline: `What should ${label} Stella tackle?`,
      body: "Drop the task here. I'll keep the work grounded in the repo."
    },
    {
      headline: 'Where should we begin?',
      body: `Give me the context and I'll answer in ${label} mode.`
    }
  ]
}

function pickCopy(copies: IntroCopy[], seed = 0): IntroCopy {
  return copies[Math.abs(seed) % copies.length] || FALLBACK_COPY[0]
}

const WORDMARK = 'STELLARIUM'

function resolveCopy(personality?: string, seed?: number): IntroCopy {
  const personalityKey = normalizeKey(personality)

  const copies = NEUTRAL_PERSONALITIES.has(personalityKey)
    ? INTRO_COPY_BY_PERSONALITY[personalityKey] || neutralCopy()
    : INTRO_COPY_BY_PERSONALITY[personalityKey] || fallbackCopyForPersonality(personalityKey)

  return pickCopy(copies, seed)
}

export function Intro({ personality, seed }: IntroProps) {
  const [mountSeed] = useState(() => Math.floor(Math.random() * 100000))
  const copy = resolveCopy(personality, mountSeed + (seed ?? 0))
  const activeMascot = useStore($activeMascotId)
  const customMascot = useStore($customMascotData)
  const mascotSrc = resolveMascotSrc(activeMascot, customMascot)
  const aui = useAui()

  const handleStarterPrompt = (prompt: string) => {
    try {
      aui.composer().setText(prompt)
    } catch {
      // safe fallback
    }
  }

  return (
    <div
      className="flex w-full min-w-0 flex-col items-center justify-center px-4 py-8 text-center text-muted-foreground sm:px-6 lg:px-8 animate-in fade-in duration-300"
      data-slot="aui_intro"
    >
      <div className="w-full max-w-xl mx-auto flex flex-col items-center">
        {/* Interactive Mascot Avatar */}
        <div
          className="relative mb-3 group cursor-pointer"
          onClick={() => {
            window.location.hash = '#/settings?tab=appearance'
          }}
          title="Click to customize avatar in Appearance settings"
        >
          <div className="size-20 rounded-2xl p-1 bg-gradient-to-br from-[#9d72ff]/40 via-purple-500/20 to-transparent border border-primary/30 shadow-[0_0_24px_rgba(157,114,255,0.3)] group-hover:scale-105 transition-all duration-300">
            <img alt="Stella Mascot Avatar" className="size-full rounded-xl object-cover" src={mascotSrc} />
          </div>
          <span className="absolute -bottom-1 -right-1 flex size-5 items-center justify-center rounded-full bg-[#9d72ff] text-[10px] text-white font-bold shadow-[0_0_8px_rgba(157,114,255,0.8)]">
            ✦
          </span>
        </div>

        {/* Modern Stellar Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-[#9d72ff]/10 border border-[#9d72ff]/30 text-xs font-semibold text-[#b794f6] mb-3 shadow-[0_0_20px_rgba(157,114,255,0.25)]">
          <span>✦</span>
          <span>STELLARIUM STUDIO · READY</span>
          <span>✦</span>
        </div>

        {/* Hero Title */}
        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight bg-gradient-to-br from-white via-purple-100 to-purple-400 bg-clip-text text-transparent mb-2">
          Welcome back, Master Ilunaa
        </h1>

        <p className="text-xs sm:text-sm text-muted-foreground/80 max-w-md mx-auto leading-relaxed mb-8">
          What shall we explore, build, or analyze together today? Drop a thought, code, or command to begin.
        </p>

        {/* Modern Quick Starter Cards Grid */}
        <div className="w-full grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
          <div
            className="group relative rounded-xl border border-white/5 bg-white/[0.02] p-3.5 hover:border-primary/40 hover:bg-primary/[0.04] transition-all duration-200 cursor-pointer shadow-sm hover:shadow-[0_0_16px_rgba(157,114,255,0.15)]"
            onClick={() => handleStarterPrompt('Inspect current repository architecture and run test builds.')}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <span className="text-base p-1.5 rounded-lg bg-primary/10 text-primary">💻</span>
              <span className="text-xs font-semibold text-foreground group-hover:text-primary transition-colors">Coding Studio</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-normal">
              Inspect code, debug errors, and run autonomous terminal builds.
            </p>
          </div>

          <div
            className="group relative rounded-xl border border-white/5 bg-white/[0.02] p-3.5 hover:border-primary/40 hover:bg-primary/[0.04] transition-all duration-200 cursor-pointer shadow-sm hover:shadow-[0_0_16px_rgba(157,114,255,0.15)]"
            onClick={() => handleStarterPrompt('Analyze documentation and summarize core architectural guidelines.')}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <span className="text-base p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400">🔍</span>
              <span className="text-xs font-semibold text-foreground group-hover:text-emerald-400 transition-colors">Deep Research</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-normal">
              Analyze long documents, crawl papers, and synthesize citations.
            </p>
          </div>

          <div
            className="group relative rounded-xl border border-white/5 bg-white/[0.02] p-3.5 hover:border-primary/40 hover:bg-primary/[0.04] transition-all duration-200 cursor-pointer shadow-sm hover:shadow-[0_0_16px_rgba(157,114,255,0.15)]"
            onClick={() => handleStarterPrompt('Brainstorm ideas and design concepts for Project Stella.')}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <span className="text-base p-1.5 rounded-lg bg-sky-500/10 text-sky-400">🎨</span>
              <span className="text-xs font-semibold text-foreground group-hover:text-sky-400 transition-colors">Creative Sandbox</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-normal">
              Brainstorm new concepts, design systems, and creative copy.
            </p>
          </div>

          <div
            className="group relative rounded-xl border border-white/5 bg-white/[0.02] p-3.5 hover:border-primary/40 hover:bg-primary/[0.04] transition-all duration-200 cursor-pointer shadow-sm hover:shadow-[0_0_16px_rgba(157,114,255,0.15)]"
            onClick={() => {
              window.location.hash = '#/profiles'
            }}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <span className="text-base p-1.5 rounded-lg bg-amber-500/10 text-amber-400">⚡</span>
              <span className="text-xs font-semibold text-foreground group-hover:text-amber-400 transition-colors">Agent Forge</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-normal">
              Customize personas, manage memory vaults, and switch active roles.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
