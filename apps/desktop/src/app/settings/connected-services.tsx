import { useEffect, useState } from 'react'

import { runInTerminal } from '@/app/right-sidebar/store'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { hermesApi } from '@/hermes'
import { CheckCircle2, ExternalLink, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'

interface ServiceStatus {
  spotify?: {
    connected?: boolean
    display_name?: string
    product?: string
    active_device?: string
    track?: string
    artist?: string
    is_playing?: boolean
  }
  mal?: {
    connected?: boolean
    username?: string
    watching?: number
    completed?: number
  }
}

export function ConnectedServicesCard() {
  const [data, setData] = useState<ServiceStatus | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchStatus = async () => {
    try {
      setLoading(true)
      const res = await hermesApi<ServiceStatus>({
        path: '/api/stella/connect/status',
        method: 'GET'
      })
      setData(res)
    } catch {
      // Ignored if offline
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchStatus()
  }, [])

  const handleConnect = (service: 'spotify' | 'mal') => {
    runInTerminal(`stella connect ${service}`)
  }

  const spotify = data?.spotify
  const mal = data?.mal

  return (
    <div className="mb-6 space-y-3">
      <div className="flex items-center justify-between px-0.5">
        <div>
          <h3 className="text-sm font-semibold text-foreground">✦ Connected Entertainment & Services</h3>
          <p className="text-xs text-muted-foreground">
            Zero-config OAuth integrations for music control and anime tracking.
          </p>
        </div>
        <Button
          className="size-7 p-0 text-muted-foreground hover:text-foreground"
          onClick={() => void fetchStatus()}
          size="sm"
          variant="ghost"
        >
          <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {/* Spotify Service Card */}
        <div className="relative flex flex-col justify-between rounded-xl border border-border/80 bg-card/60 p-3.5 backdrop-blur-sm transition-colors hover:border-border">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
                  <Codicon name="music" size="1.1rem" />
                </span>
                <div>
                  <h4 className="text-xs font-semibold text-foreground">Spotify</h4>
                  <p className="text-[11px] text-muted-foreground">Playback, queue & search</p>
                </div>
              </div>
              {spotify?.connected ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                  <CheckCircle2 className="size-2.5" />
                  Connected
                </span>
              ) : (
                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                  Not Connected
                </span>
              )}
            </div>

            <div className="mt-3 min-h-[38px] text-[11px]">
              {spotify?.connected ? (
                <div className="space-y-0.5">
                  <div className="font-medium text-foreground">
                    {spotify.display_name}{' '}
                    {spotify.product && <span className="text-muted-foreground capitalize">({spotify.product})</span>}
                  </div>
                  {spotify.track ? (
                    <div className="truncate text-emerald-400/90">
                      ▶ {spotify.artist} - {spotify.track}
                    </div>
                  ) : (
                    <div className="text-muted-foreground">
                      Device: {spotify.active_device || 'Ready to stream'}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-muted-foreground">
                  Stream music, Leo/need, and Robin tracks directly through Stella & Discord.
                </p>
              )}
            </div>
          </div>

          <div className="mt-3 pt-2">
            <Button
              className="w-full text-xs font-medium"
              onClick={() => handleConnect('spotify')}
              size="sm"
              variant={spotify?.connected ? 'outline' : 'default'}
            >
              <Codicon className="mr-1.5 size-3.5" name="link-external" />
              {spotify?.connected ? 'Reconnect Spotify' : 'Connect Spotify'}
            </Button>
          </div>
        </div>

        {/* MyAnimeList Service Card */}
        <div className="relative flex flex-col justify-between rounded-xl border border-border/80 bg-card/60 p-3.5 backdrop-blur-sm transition-colors hover:border-border">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
                  <Codicon name="device-camera-video" size="1.1rem" />
                </span>
                <div>
                  <h4 className="text-xs font-semibold text-foreground">MyAnimeList</h4>
                  <p className="text-[11px] text-muted-foreground">Anime tracking & episodes</p>
                </div>
              </div>
              {mal?.connected ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-400">
                  <CheckCircle2 className="size-2.5" />
                  Connected
                </span>
              ) : (
                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                  Not Connected
                </span>
              )}
            </div>

            <div className="mt-3 min-h-[38px] text-[11px]">
              {mal?.connected ? (
                <div className="space-y-0.5">
                  <div className="font-medium text-foreground">@{mal.username}</div>
                  <div className="text-muted-foreground">
                    {mal.watching ?? 0} watching · {mal.completed ?? 0} completed
                  </div>
                </div>
              ) : (
                <p className="text-muted-foreground">
                  Track anime progress, seasonal releases, and user lists with zero config.
                </p>
              )}
            </div>
          </div>

          <div className="mt-3 pt-2">
            <Button
              className="w-full text-xs font-medium"
              onClick={() => handleConnect('mal')}
              size="sm"
              variant={mal?.connected ? 'outline' : 'default'}
            >
              <Codicon className="mr-1.5 size-3.5" name="link-external" />
              {mal?.connected ? 'Reconnect MyAnimeList' : 'Connect MyAnimeList'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
