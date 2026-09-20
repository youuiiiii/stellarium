import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { SanitizedInput } from '@/components/ui/sanitized-input'
import { AlertCircle, CheckCircle2, Download, Loader2, RefreshCw, ShieldLock } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'
import { refreshProfiles } from '@/store/profile'

interface DetectedInstallation {
  path: string
  exists: boolean
  is_active_hermes_home: boolean
  has_config: boolean
  has_soul: boolean
  has_memories: boolean
  has_skills: boolean
  has_cron: boolean
  has_sessions: boolean
  named_profiles: string[]
}

interface DetectResponse {
  detected: DetectedInstallation[]
}

interface MigrationExecuteResponse {
  success: boolean
  manifest: {
    migration_id: string
    source_path: string
    target_profile_id: string
    copied_files_count: number
    conflicts_resolved: number
  }
}

const AVAILABLE_COMPONENTS = [
  { id: 'config', label: 'Configuration & Settings', desc: 'Models, providers, preferences (secrets filtered)' },
  { id: 'soul', label: 'Persona & Identity', desc: 'SOUL.md and custom agent directives' },
  { id: 'memories', label: 'Persistent Memories', desc: 'User notes and remembered operational facts' },
  { id: 'skills', label: 'Custom Skills', desc: 'Procedural custom skills and user workflows' },
  { id: 'cron', label: 'Scheduled Jobs', desc: 'Automated recurring cron jobs' },
  { id: 'sessions', label: 'Conversation Sessions', desc: 'Session transcripts and message history' }
]

export function HermesMigrationDialog({
  onClose,
  open,
  targetProfileId = 'stella'
}: {
  onClose: () => void
  open: boolean
  targetProfileId?: string
}) {
  const [loading, setLoading] = useState(true)
  const [detected, setDetected] = useState<DetectedInstallation[]>([])
  const [selectedSource, setSelectedSource] = useState('')
  const [selectedComponents, setSelectedComponents] = useState<string[]>([
    'config',
    'soul',
    'memories',
    'skills',
    'cron'
  ])
  const [overwrite, setOverwrite] = useState(false)
  const [migrating, setMigrating] = useState(false)
  const [result, setResult] = useState<MigrationExecuteResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    setResult(null)
    setError(null)
    setMigrating(false)
    void scanHermes()
  }, [open])

  async function scanHermes() {
    setLoading(true)
    setError(null)
    try {
      if (window.hermesDesktop?.api) {
        const resp = await window.hermesDesktop.api<DetectResponse>({
          path: '/api/stella/migration/detect',
          method: 'GET'
        })
        const valid = resp?.detected ?? []
        setDetected(valid)
        if (valid.length > 0) {
          setSelectedSource(valid[0].path)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not scan for Hermes installations.')
    } finally {
      setLoading(false)
    }
  }

  function toggleComponent(id: string) {
    setSelectedComponents(prev => (prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]))
  }

  async function handleExecute() {
    if (!selectedSource.trim()) {
      setError('Please select or specify a source Hermes installation path.')
      return
    }
    if (selectedComponents.length === 0) {
      setError('Please select at least one component to import.')
      return
    }

    setMigrating(true)
    setError(null)

    try {
      if (window.hermesDesktop?.api) {
        const resp = await window.hermesDesktop.api<MigrationExecuteResponse>({
          path: '/api/stella/migration/execute',
          method: 'POST',
          body: {
            source_path: selectedSource.trim(),
            target_profile_id: targetProfileId,
            components: selectedComponents,
            overwrite,
            include_profiles: false
          }
        })
        setResult(resp)
        notify({ message: 'Hermes data migrated successfully into Stella profile!' })
        await refreshProfiles()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Migration failed.')
      notifyError(err, 'Migration failed')
    } finally {
      setMigrating(false)
    }
  }

  return (
    <Dialog onOpenChange={open => !open && onClose()} open={open}>
      <DialogContent className="max-w-xl border-white/[0.08] bg-[#0c0a18]/95 p-6 backdrop-blur-2xl text-foreground shadow-[0_0_40px_rgba(157,114,255,0.15)]">
        <DialogHeader className="gap-1.5 border-b border-white/[0.06] pb-4">
          <div className="flex items-center gap-2 text-[#9d72ff]">
            <ShieldLock className="size-5" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-[#9d72ff]/90">
              Stella Safe Migration Engine
            </span>
          </div>
          <DialogTitle className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            Import Hermes into Stella
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Strict read-only import. Your existing Hermes installation remains 100% untouched. Secrets and raw environment keys are safely filtered.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-10 gap-3">
            <Loader2 className="size-6 animate-spin text-[#9d72ff]" />
            <p className="text-xs text-muted-foreground">Scanning system for Hermes installations…</p>
          </div>
        ) : result ? (
          <div className="py-6 flex flex-col items-center gap-4 text-center">
            <div className="size-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center border border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.3)]">
              <CheckCircle2 className="size-6" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Migration Complete!</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Successfully imported {result.manifest.copied_files_count} files into profile{' '}
                <span className="font-mono text-[#9d72ff]">{result.manifest.target_profile_id}</span>.
              </p>
            </div>
            <DialogFooter className="w-full mt-4">
              <Button className="w-full bg-[#9d72ff] hover:bg-[#8b5cf6] text-white" onClick={onClose}>
                Finish & View Profile
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="grid gap-5 py-2">
            {/* Detected Installations */}
            <div className="grid gap-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-white/90">Source Hermes Installation</span>
                <button
                  className="flex items-center gap-1 text-[11px] text-[#9d72ff] hover:underline"
                  onClick={scanHermes}
                  type="button"
                >
                  <RefreshCw className="size-3" /> Rescan
                </button>
              </div>

              {detected.length > 0 ? (
                <div className="grid gap-2">
                  {detected.map(item => (
                    <div
                      className={`flex items-start justify-between p-3 rounded-xl border transition-all cursor-pointer ${
                        selectedSource === item.path
                          ? 'border-[#9d72ff]/50 bg-[#9d72ff]/10 shadow-[0_0_12px_rgba(157,114,255,0.15)]'
                          : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04]'
                      }`}
                      key={item.path}
                      onClick={() => setSelectedSource(item.path)}
                    >
                      <div className="grid gap-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-white font-medium">{item.path}</span>
                          {item.is_active_hermes_home && (
                            <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-400 border border-emerald-500/30">
                              Active
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                          <span>Config: {item.has_config ? '✓' : '—'}</span>
                          <span>Memories: {item.has_memories ? '✓' : '—'}</span>
                          <span>Skills: {item.has_skills ? '✓' : '—'}</span>
                          <span>Cron: {item.has_cron ? '✓' : '—'}</span>
                        </div>
                      </div>
                      <input
                        checked={selectedSource === item.path}
                        className="mt-1 accent-[#9d72ff]"
                        name="hermes-source"
                        onChange={() => setSelectedSource(item.path)}
                        type="radio"
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-3 rounded-xl border border-dashed border-white/[0.1] bg-white/[0.01] text-xs text-muted-foreground">
                  No default installation detected automatically. Specify path below:
                </div>
              )}

              <SanitizedInput
                className="mt-1 font-mono text-xs bg-black/40 border-white/[0.08]"
                onValueChange={(val: string) => setSelectedSource(val)}
                placeholder="C:\Users\...\.hermes"
                sanitize={v => v}
                value={selectedSource}
              />
            </div>

            {/* Components Selection */}
            <div className="grid gap-2">
              <span className="text-xs font-semibold text-white/90">Components to Import</span>
              <div className="grid grid-cols-2 gap-2">
                {AVAILABLE_COMPONENTS.map(comp => {
                  const active = selectedComponents.includes(comp.id)
                  return (
                    <div
                      className={`flex items-start gap-2.5 p-2.5 rounded-lg border transition-all cursor-pointer ${
                        active
                          ? 'border-[#9d72ff]/40 bg-[#9d72ff]/10 text-white'
                          : 'border-white/[0.05] bg-white/[0.02] text-muted-foreground hover:bg-white/[0.04]'
                      }`}
                      key={comp.id}
                      onClick={() => toggleComponent(comp.id)}
                    >
                      <input
                        checked={active}
                        className="mt-0.5 accent-[#9d72ff]"
                        onChange={() => toggleComponent(comp.id)}
                        type="checkbox"
                      />
                      <div className="grid gap-0.5">
                        <span className="text-xs font-medium leading-tight">{comp.label}</span>
                        <span className="text-[10px] text-muted-foreground leading-tight">{comp.desc}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Conflict Option */}
            <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer pt-1">
              <input
                checked={overwrite}
                className="accent-[#9d72ff]"
                onChange={e => setOverwrite(e.target.checked)}
                type="checkbox"
              />
              <span>Overwrite conflicting files in target profile (automatically backed up)</span>
            </label>

            {error && (
              <div className="flex items-center gap-2 rounded-lg bg-rose-500/10 border border-rose-500/30 p-2.5 text-xs text-rose-300">
                <AlertCircle className="size-4 shrink-0 text-rose-400" />
                <span>{error}</span>
              </div>
            )}

            <DialogFooter className="mt-2 gap-2">
              <Button disabled={migrating} onClick={onClose} variant="ghost">
                Cancel
              </Button>
              <Button
                className="bg-gradient-to-r from-[#9d72ff] to-[#7c3aed] text-white hover:opacity-90 shadow-[0_0_15px_rgba(157,114,255,0.3)] gap-2"
                disabled={migrating || !selectedSource.trim()}
                onClick={handleExecute}
              >
                {migrating ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" />
                    Migrating…
                  </>
                ) : (
                  <>
                    <Download className="size-3.5" />
                    Start 1-Click Import
                  </>
                )}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
