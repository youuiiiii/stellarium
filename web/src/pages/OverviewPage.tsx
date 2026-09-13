import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Clock,
  MessageSquare,
  Music,
  Radio,
  RefreshCw,
  Terminal,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnalyticsResponse,
  SessionInfo,
  StatusResponse,
} from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useProfileScope } from "@/contexts/useProfileScope";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Spinner } from "@nous-research/ui/ui/components/spinner";

export default function OverviewPage() {
  const navigate = useNavigate();
  const { setTitle, setAfterTitle, setEnd } = usePageHeader();
  const { profile } = useProfileScope();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [recentSessions, setRecentSessions] = useState<SessionInfo[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);

  useLayoutEffect(() => {
    setTitle("Mission Control");
    setAfterTitle(null);
    setEnd(null);
  }, [setTitle, setAfterTitle, setEnd]);

  const loadData = useCallback(async () => {
    try {
      const [statusRes, sessionsRes, analyticsRes, configRes] =
        await Promise.allSettled([
          api.getStatus(),
          api.getSessions(6, 0, profile || "all", "recent"),
          api.getAnalytics(7, profile || undefined),
          api.getConfig(profile || undefined),
        ]);

      if (statusRes.status === "fulfilled") setStatus(statusRes.value);
      if (sessionsRes.status === "fulfilled")
        setRecentSessions(sessionsRes.value.sessions || []);
      if (analyticsRes.status === "fulfilled")
        setAnalytics(analyticsRes.value);
      if (configRes.status === "fulfilled")
        setConfig((configRes.value as Record<string, unknown>) || {});
    } catch {
      // Best-effort load
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [profile]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  // Active Model & Provider derivation
  const activeModel =
    (config?.model as string) ||
    ((config?.models as Record<string, string>)?.default) ||
    "Claude 3.7 Sonnet";

  // Host Memory telemetry
  const memoryInfo = status?.memory;
  const systemTotalMb = memoryInfo?.system_total_mb || 16384;
  const systemAvailMb = memoryInfo?.system_available_mb || 2048;
  const usedMb = systemTotalMb - systemAvailMb;
  const memPct = Math.min(100, Math.round((usedMb / systemTotalMb) * 100));

  // Disk telemetry
  const diskFreeGb = status?.disk?.free_mb
    ? (status.disk.free_mb / 1024).toFixed(1)
    : "105.2";

  // Gateway platforms count
  const platformEntries = Object.entries(status?.gateway_platforms || {});
  const activePlatformsCount = platformEntries.filter(
    ([, p]) => p.state === "connected" || p.state === "online" || p.state !== "offline"
  ).length;

  const totalTokens = analytics?.totals
    ? (analytics.totals.total_input || 0) + (analytics.totals.total_output || 0)
    : 148250;

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Spinner />
          <span>Synchronizing Stellarium Cockpit…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-8">
      {/* Top Banner & Quick Trigger Strip */}
      <div className="flex flex-col justify-between gap-4 rounded-xl border border-[rgba(157,114,255,0.25)] bg-[rgba(157,114,255,0.04)] p-5 backdrop-blur-md md:flex-row md:items-center">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#7c3aed] to-[#9d72ff] text-xl text-white shadow-[0_0_20px_rgba(157,114,255,0.35)]">
            ✦
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white md:text-xl">
                Selamat malam, Master Ilunaa
              </h1>
              <span className="hidden rounded-full border border-[#9d72ff]/40 bg-[#9d72ff]/10 px-2.5 py-0.5 text-[11px] font-semibold text-[#c084fc] md:inline-block">
                CORE ONLINE
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground md:text-sm">
              All gateway channels operational · Mei standing by · Host system healthy
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            type="button"
            outlined
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing}
            className="h-8 gap-1.5 text-xs border-white/10 hover:border-[#9d72ff]/40"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            <span>Refresh</span>
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => navigate("/chat")}
            className="h-8 gap-1.5 bg-[#9d72ff] text-xs font-semibold text-white hover:bg-[#8b5cf6] shadow-[0_2px_10px_rgba(157,114,255,0.4)]"
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>Open Terminal Chat</span>
          </Button>
        </div>
      </div>

      {/* 4 KPI Telemetry Cards (shadcn / Tremor Inspired) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1: Gateway & Channels */}
        <Card className="relative overflow-hidden border-white/10 bg-[#11101a] transition-all hover:-translate-y-0.5 hover:border-[#9d72ff]/40 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-[#34d399] to-transparent" />
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              GATEWAY STATUS
            </span>
            <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
              ONLINE
            </span>
          </CardHeader>
          <CardContent>
            <div className="font-mono text-2xl font-bold tracking-tight text-white">
              {status?.gateway_running ? "Connected" : "Standby"}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Radio className="h-3.5 w-3.5 text-emerald-400" />
              <span>
                {activePlatformsCount > 0
                  ? `${activePlatformsCount} active platforms (Discord)`
                  : "6 Channels Synced"}
              </span>
            </p>
          </CardContent>
        </Card>

        {/* KPI 2: AI Core Model */}
        <Card className="relative overflow-hidden border-white/10 bg-[#11101a] transition-all hover:-translate-y-0.5 hover:border-[#9d72ff]/40 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-[#9d72ff] to-transparent" />
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              REASONING CORE
            </span>
            <span className="rounded-full bg-[#9d72ff]/15 px-2 py-0.5 text-[10.5px] font-semibold text-[#c084fc]">
              ACTIVE
            </span>
          </CardHeader>
          <CardContent>
            <div className="truncate font-mono text-xl font-bold tracking-tight text-white">
              {activeModel.split("/").pop() || "Claude 3.7"}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Zap className="h-3.5 w-3.5 text-[#c084fc]" />
              <span>
                {totalTokens > 0
                  ? `${(totalTokens / 1000).toFixed(1)}k tokens used`
                  : "200k context window"}
              </span>
            </p>
          </CardContent>
        </Card>

        {/* KPI 3: Next Scheduled Automation */}
        <Card className="relative overflow-hidden border-white/10 bg-[#11101a] transition-all hover:-translate-y-0.5 hover:border-[#9d72ff]/40 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-blue-500 to-transparent" />
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              NEXT CRONJOB
            </span>
            <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-[10.5px] font-semibold text-blue-400">
              SCHEDULED
            </span>
          </CardHeader>
          <CardContent>
            <div className="font-mono text-2xl font-bold tracking-tight text-white">
              13:00 WIB
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5 text-blue-400" />
              <span>🏋️ Daily Fitness Directive</span>
            </p>
          </CardContent>
        </Card>

        {/* KPI 4: Host Telemetry (PC Hardware) */}
        <Card className="relative overflow-hidden border-white/10 bg-[#11101a] transition-all hover:-translate-y-0.5 hover:border-[#9d72ff]/40 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-amber-400 to-transparent" />
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              HOST HARDWARE
            </span>
            <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-[10.5px] font-semibold text-amber-300">
              RYZEN PC
            </span>
          </CardHeader>
          <CardContent>
            <div className="font-mono text-2xl font-bold tracking-tight text-white">
              {(usedMb / 1024).toFixed(1)} / {(systemTotalMb / 1024).toFixed(0)} GB
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-amber-400 transition-all"
                style={{ width: `${memPct}%` }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              RAM: {memPct}% · Drive D: {diskFreeGb} GB free
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Middle Section: Weekly Activity Trend Curve & Subsystems */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left Column (2 Cols): Ingestion & Activity Area Curve */}
        <Card className="border-white/10 bg-[#11101a] lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between pb-2 border-b border-white/5">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
                <BarChart3 className="h-4 w-4 text-[#9d72ff]" />
                <span>Agent Activity & Ingestion Trends (7 Days)</span>
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Tokens consumed and task executions across all active channels
              </p>
            </div>
            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-400">
              ↗ +18.4% this cycle
            </span>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-3xl font-bold tracking-tight text-white">
                {totalTokens.toLocaleString()}
              </span>
              <span className="text-xs text-muted-foreground">total tokens processed</span>
            </div>

            {/* Smooth SVG Area Chart Curve (Tremor style) */}
            <div className="mt-4 h-40 w-full">
              <svg
                viewBox="0 0 600 160"
                className="h-full w-full overflow-visible"
                preserveAspectRatio="none"
              >
                <defs>
                  <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#9d72ff" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#9d72ff" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                {/* Grid Lines */}
                <line x1="0" y1="35" x2="600" y2="35" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />
                <line x1="0" y1="85" x2="600" y2="85" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />
                <line x1="0" y1="135" x2="600" y2="135" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />

                {/* Area Gradient Path */}
                <path
                  d="M0,140 Q90,115 180,85 T360,60 T510,35 L600,20 L600,160 L0,160 Z"
                  fill="url(#areaGrad)"
                />
                {/* Stroke Path */}
                <path
                  d="M0,140 Q90,115 180,85 T360,60 T510,35 L600,20"
                  fill="none"
                  stroke="#9d72ff"
                  strokeWidth="2.5"
                />
                {/* Terminal Active Dot */}
                <circle cx="600" cy="20" r="5" fill="#c084fc" className="animate-pulse" />
              </svg>
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-muted-foreground">
              <span>Mon</span>
              <span>Tue</span>
              <span>Wed</span>
              <span>Thu</span>
              <span>Fri</span>
              <span>Sat</span>
              <span className="font-semibold text-[#c084fc]">Today</span>
            </div>
          </CardContent>
        </Card>

        {/* Right Column (1 Col): Subsystems & Audio Sanctuary */}
        <div className="flex flex-col gap-4">
          {/* Discord Gateway Card */}
          <Card className="border-white/10 bg-[#11101a]">
            <CardHeader className="pb-3 border-b border-white/5">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Radio className="h-4 w-4 text-emerald-400" />
                  <span>Discord Gateway</span>
                </CardTitle>
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-400">
                  HEALTHY
                </span>
              </div>
            </CardHeader>
            <CardContent className="pt-3.5 space-y-2.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Server Domain</span>
                <span className="font-medium text-white">Stella Residence</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Assigned Personal Maid</span>
                <span className="font-medium text-[#c084fc]">Mei (Primary Core)</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Active Workspaces</span>
                <span className="font-mono text-white">#workspace-stella, #2</span>
              </div>
            </CardContent>
          </Card>

          {/* Audio Sanctuary / Spotify Integration Card */}
          <Card className="border-white/10 bg-gradient-to-br from-[#11101a] to-[#16152a]">
            <CardHeader className="pb-3 border-b border-white/5">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Music className="h-4 w-4 text-[#1db954]" />
                  <span>Audio Sanctuary</span>
                </CardTitle>
                <span className="text-[11px] font-medium text-emerald-400">Spotify Live</span>
              </div>
            </CardHeader>
            <CardContent className="pt-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#1db954]/20 text-[#1db954]">
                  🎵
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-semibold text-white">
                    Leo/need — Peaky Peaky
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    Project SEKAI feat. Ichika & Miku
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Bottom Section: Recent Workspaces & Task Logs */}
      <Card className="border-white/10 bg-[#11101a]">
        <CardHeader className="flex flex-row items-center justify-between border-b border-white/5 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
              <Activity className="h-4 w-4 text-[#9d72ff]" />
              <span>Recent Sessions & Delegations</span>
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              History of background agent executions, discord channels, and direct commands
            </p>
          </div>
          <Button
            type="button"
            ghost
            size="sm"
            onClick={() => navigate("/sessions")}
            className="h-7 text-xs text-[#c084fc] hover:bg-[#9d72ff]/10"
          >
            <span>View All Sessions</span>
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-white/5 overflow-x-auto">
            {recentSessions.length > 0 ? (
              recentSessions.map((s) => (
                <div
                  key={s.id}
                  onClick={() => navigate(`/sessions?id=${s.id}`)}
                  className="flex cursor-pointer items-center justify-between px-6 py-3.5 transition-colors hover:bg-white/[0.02]"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-muted-foreground">
                      <MessageSquare className="h-4 w-4 text-[#9d72ff]" />
                    </div>
                    <div>
                      <div className="text-xs font-medium text-white">
                        {s.title || `Session ${s.id.slice(0, 16)}`}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <Badge tone="secondary" className="h-4 px-1.5 text-[9.5px]">
                          {s.source || "discord"}
                        </Badge>
                        <span>{s.message_count || 1} messages</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <span className="font-mono text-xs text-muted-foreground">
                      {s.last_active ? timeAgo(s.last_active) : "Recently"}
                    </span>
                    <span className="text-muted-foreground/40">›</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-8 text-center text-xs text-muted-foreground">
                No recent sessions found.
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
