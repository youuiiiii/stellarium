import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Clock,
  Cpu,
  Layers,
  MessageSquare,
  Package,
  Plug,
  Radio,
  RefreshCw,
  Terminal,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnalyticsDailyEntry,
  AnalyticsResponse,
  CronJob,
  McpServer,
  SessionInfo,
  SkillInfo,
  StatusResponse,
} from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useProfileScope } from "@/contexts/useProfileScope";
import { Spinner } from "@nous-research/ui/ui/components/spinner";

function getDynamicGreeting(profileName?: string) {
  const hour = new Date().getHours();
  let timeStr = "Good evening";
  if (hour >= 5 && hour < 12) timeStr = "Good morning";
  else if (hour >= 12 && hour < 18) timeStr = "Good afternoon";

  if (profileName && profileName !== "default" && profileName !== "all") {
    return `${timeStr}, ${profileName}`;
  }
  return `${timeStr}, Master Ilunaa`;
}

function generateAreaPath(daily: AnalyticsDailyEntry[] = []): {
  areaPath: string;
  strokePath: string;
  maxVal: number;
  points: Array<{ x: number; y: number; label: string; tokens: number }>;
} {
  if (!daily || daily.length === 0) {
    return {
      areaPath: "M0,140 L600,140 L600,160 L0,160 Z",
      strokePath: "M0,140 L600,140",
      maxVal: 0,
      points: [],
    };
  }

  const values = daily.map(
    (d) => (d.input_tokens || 0) + (d.output_tokens || 0)
  );
  const maxVal = Math.max(...values, 1000);
  const n = daily.length;
  const width = 600;
  const height = 110;
  const topPadding = 25;

  const pts = daily.map((d, i) => {
    const x = n > 1 ? (i / (n - 1)) * width : width / 2;
    const val = (d.input_tokens || 0) + (d.output_tokens || 0);
    const y = topPadding + (height - (val / maxVal) * height);
    return {
      x,
      y,
      label: d.day ? d.day.slice(5) : `D${i + 1}`,
      tokens: val,
    };
  });

  let pathD = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1];
    const curr = pts[i];
    const cX = (prev.x + curr.x) / 2;
    pathD += ` C${cX},${prev.y} ${cX},${curr.y} ${curr.x},${curr.y}`;
  }

  const strokePath = pathD;
  const areaPath = `${pathD} L${pts[pts.length - 1].x},160 L${pts[0].x},160 Z`;

  return { areaPath, strokePath, maxVal, points: pts };
}

export default function OverviewPage() {
  const navigate = useNavigate();
  const { setTitle, setAfterTitle, setEnd } = usePageHeader();
  const { profile } = useProfileScope();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [recentSessions, setRecentSessions] = useState<SessionInfo[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);

  useLayoutEffect(() => {
    setTitle("Mission Control");
    setAfterTitle(null);
    setEnd(null);
  }, [setTitle, setAfterTitle, setEnd]);

  const loadData = useCallback(async () => {
    try {
      const [
        statusRes,
        cronRes,
        sessionsRes,
        analyticsRes,
        configRes,
        skillsRes,
        mcpRes,
      ] = await Promise.allSettled([
        api.getStatus(),
        api.getCronJobs(profile || "all"),
        api.getSessions(6, 0, profile || "all", "recent"),
        api.getAnalytics(7, profile || undefined),
        api.getConfig(profile || undefined),
        api.getSkills(profile || undefined),
        api.getMcpServers(),
      ]);

      if (statusRes.status === "fulfilled") setStatus(statusRes.value);
      if (cronRes.status === "fulfilled") setCronJobs(cronRes.value || []);
      if (sessionsRes.status === "fulfilled")
        setRecentSessions(sessionsRes.value.sessions || []);
      if (analyticsRes.status === "fulfilled")
        setAnalytics(analyticsRes.value);
      if (configRes.status === "fulfilled")
        setConfig((configRes.value as Record<string, unknown>) || {});
      if (skillsRes.status === "fulfilled") setSkills(skillsRes.value || []);
      if (mcpRes.status === "fulfilled")
        setMcpServers(mcpRes.value.servers || []);
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

  // 1. Dynamic Model info
  const activeModel =
    (config?.model as string) ||
    ((config?.models as Record<string, string>)?.default) ||
    "Auto-Router";

  // 2. Dynamic Memory telemetry
  const memoryInfo = status?.memory;
  const systemTotalMb = memoryInfo?.system_total_mb || 16384;
  const systemAvailMb = memoryInfo?.system_available_mb || 2048;
  const usedMb = Math.max(0, systemTotalMb - systemAvailMb);
  const memPct = Math.min(100, Math.round((usedMb / systemTotalMb) * 100));

  // 3. Dynamic Disk telemetry
  const diskFreeGb = status?.disk?.free_mb
    ? (status.disk.free_mb / 1024).toFixed(1)
    : "105.2";

  // 4. Dynamic Gateway Platforms
  const platformEntries = Object.entries(status?.gateway_platforms || {});
  const activePlatformsCount = platformEntries.filter(
    ([, p]) =>
      p.state === "connected" ||
      p.state === "online" ||
      (p.state !== "offline" && p.state !== "disabled")
  ).length;

  // 5. Dynamic Cronjob / Automation
  const activeJobs = cronJobs.filter((j) => j.enabled);
  const nextJob = activeJobs.find((j) => j.next_run_at) || activeJobs[0];

  // 6. Dynamic Analytics tokens
  const totalTokens = analytics?.totals
    ? (analytics.totals.total_input || 0) + (analytics.totals.total_output || 0)
    : 0;

  // 7. Dynamic Curve Data
  const chartData = useMemo(
    () => generateAreaPath(analytics?.daily || []),
    [analytics]
  );

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-zinc-400 font-sans">
          <Spinner />
          <span>Synchronizing Mission Control Telemetry…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-8 font-sans">
      {/* Top Welcome Banner (Linear Style) */}
      <div className="flex flex-col justify-between gap-4 rounded-xl border border-white/[0.08] bg-[#11101a] p-5 shadow-[0_4px_20px_rgba(0,0,0,0.3)] md:flex-row md:items-center">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#7c3aed] to-[#9d72ff] text-xl font-bold text-white shadow-[0_0_16px_rgba(157,114,255,0.4)]">
            ✦
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-lg font-bold tracking-tight text-white md:text-xl">
                {getDynamicGreeting(profile || undefined)}
              </h1>
              <span className="rounded-full border border-[#9d72ff]/40 bg-[#9d72ff]/15 px-2.5 py-0.5 text-[11px] font-semibold text-[#c084fc]">
                {status?.gateway_running ? "GATEWAY LIVE" : "STANDBY"}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-[#9d9bb3]">
              {platformEntries.length > 0
                ? `${activePlatformsCount} of ${platformEntries.length} messaging platforms connected · Engine v${status?.version || "0.21.2"}`
                : `Engine v${status?.version || "0.21.2"} · All local systems operational`}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-xs font-medium text-white transition-all hover:border-[#9d72ff]/40 hover:bg-white/[0.06] cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin text-[#c084fc]")} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => navigate("/chat")}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-gradient-to-r from-[#7c3aed] to-[#9d72ff] px-3.5 text-xs font-semibold text-white shadow-[0_2px_10px_rgba(157,114,255,0.35)] transition-all hover:opacity-95 cursor-pointer"
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>Open Terminal Chat</span>
          </button>
        </div>
      </div>

      {/* 4 KPI Telemetry Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1: Gateway Status */}
        <div className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-white/[0.08] bg-[#11101a] p-4 transition-all hover:-translate-y-0.5 hover:border-[#34d399]/50 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-[#34d399] to-transparent" />
          <div className="flex items-center justify-between pb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#646279]">
              GATEWAY STATUS
            </span>
            <span
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
                status?.gateway_running
                  ? "bg-emerald-500/10 text-emerald-400"
                  : "bg-zinc-500/10 text-zinc-400"
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  status?.gateway_running
                    ? "bg-emerald-400 shadow-[0_0_6px_#34d399]"
                    : "bg-zinc-400"
                )}
              />
              {status?.gateway_running ? "ONLINE" : "OFFLINE"}
            </span>
          </div>
          <div>
            <div className="font-mono text-2xl font-bold tracking-tight text-white">
              {activePlatformsCount > 0
                ? `${activePlatformsCount} Connected`
                : status?.gateway_running
                ? "Active"
                : "Standby"}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-[#9d9bb3]">
              <Radio className="h-3.5 w-3.5 text-emerald-400" />
              <span>
                {platformEntries.length > 0
                  ? platformEntries.map(([k]) => k).join(", ")
                  : "Local Loopback"}
              </span>
            </p>
          </div>
        </div>

        {/* KPI 2: AI Core Model */}
        <div className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-white/[0.08] bg-[#11101a] p-4 transition-all hover:-translate-y-0.5 hover:border-[#9d72ff]/50 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-[#9d72ff] to-transparent" />
          <div className="flex items-center justify-between pb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#646279]">
              REASONING CORE
            </span>
            <span className="rounded-full bg-[#9d72ff]/15 px-2 py-0.5 text-[10.5px] font-semibold text-[#c084fc]">
              ACTIVE
            </span>
          </div>
          <div>
            <div className="truncate font-mono text-xl font-bold tracking-tight text-white">
              {activeModel.split("/").pop()}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-[#9d9bb3]">
              <Zap className="h-3.5 w-3.5 text-[#c084fc]" />
              <span>
                {totalTokens > 0
                  ? `${(totalTokens / 1000).toFixed(1)}k tokens (7d)`
                  : "Smart Auto-Routing"}
              </span>
            </p>
          </div>
        </div>

        {/* KPI 3: Next Scheduled Automation */}
        <div className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-white/[0.08] bg-[#11101a] p-4 transition-all hover:-translate-y-0.5 hover:border-blue-500/50 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-blue-500 to-transparent" />
          <div className="flex items-center justify-between pb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#646279]">
              AUTOMATION
            </span>
            <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-[10.5px] font-semibold text-blue-400">
              {activeJobs.length > 0 ? `${activeJobs.length} JOBS` : "IDLE"}
            </span>
          </div>
          <div>
            <div className="truncate font-mono text-2xl font-bold tracking-tight text-white">
              {nextJob
                ? nextJob.schedule_display || nextJob.next_run_at || "Active"
                : "No Jobs"}
            </div>
            <p className="mt-1 flex items-center gap-1.5 truncate text-xs text-[#9d9bb3]">
              <Clock className="h-3.5 w-3.5 text-blue-400 shrink-0" />
              <span className="truncate">
                {nextJob?.name || nextJob?.prompt?.slice(0, 24) || "None scheduled"}
              </span>
            </p>
          </div>
        </div>

        {/* KPI 4: Host Telemetry */}
        <div className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-white/[0.08] bg-[#11101a] p-4 transition-all hover:-translate-y-0.5 hover:border-amber-400/50 hover:shadow-lg">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-amber-400 to-transparent" />
          <div className="flex items-center justify-between pb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#646279]">
              HOST VITALS
            </span>
            <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-[10.5px] font-semibold text-amber-300">
              {status?.memory?.pressure ? `MEM ${status.memory.pressure.toUpperCase()}` : "NORMAL"}
            </span>
          </div>
          <div>
            <div className="font-mono text-2xl font-bold tracking-tight text-white">
              {(usedMb / 1024).toFixed(1)} / {(systemTotalMb / 1024).toFixed(0)} GB
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-amber-400 transition-all"
                style={{ width: `${memPct}%` }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-[#9d9bb3]">
              RAM: {memPct}% · Storage: {diskFreeGb} GB free
            </p>
          </div>
        </div>
      </div>

      {/* Middle Section: Activity Curve + Subsystems */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left Column: Dynamic Ingestion Curve */}
        <div className="rounded-xl border border-white/[0.08] bg-[#11101a] p-5 shadow-[0_4px_20px_rgba(0,0,0,0.3)] lg:col-span-2">
          <div className="flex items-center justify-between border-b border-white/5 pb-3">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <BarChart3 className="h-4 w-4 text-[#9d72ff]" />
                <span>Token Ingestion & Activity Trends (7 Days)</span>
              </h2>
              <p className="text-xs text-[#9d9bb3]">
                Daily token throughput across interactive chat and automated runs
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate("/analytics")}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[#c084fc] transition-colors hover:bg-[#9d72ff]/10 cursor-pointer"
            >
              <span>Full Analytics</span>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="pt-5">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-3xl font-bold tracking-tight text-white">
                {totalTokens > 0 ? totalTokens.toLocaleString() : "0"}
              </span>
              <span className="text-xs text-[#9d9bb3]">total tokens in period</span>
            </div>

            {/* Render dynamically calculated SVG spline */}
            <div className="mt-4 h-40 w-full">
              <svg
                viewBox="0 0 600 160"
                className="h-full w-full overflow-visible"
                preserveAspectRatio="none"
              >
                <defs>
                  <linearGradient id="dynamicAreaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#9d72ff" stopOpacity="0.38" />
                    <stop offset="100%" stopColor="#9d72ff" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                <line x1="0" y1="35" x2="600" y2="35" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />
                <line x1="0" y1="85" x2="600" y2="85" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />
                <line x1="0" y1="135" x2="600" y2="135" stroke="rgba(255,255,255,0.04)" strokeDasharray="3,3" />

                <path d={chartData.areaPath} fill="url(#dynamicAreaGrad)" />
                <path d={chartData.strokePath} fill="none" stroke="#9d72ff" strokeWidth="2.5" />

                {chartData.points.map((pt, idx) => (
                  <circle
                    key={idx}
                    cx={pt.x}
                    cy={pt.y}
                    r={idx === chartData.points.length - 1 ? 4.5 : 3}
                    fill={idx === chartData.points.length - 1 ? "#c084fc" : "#9d72ff"}
                  />
                ))}
              </svg>
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-[#9d9bb3]">
              {chartData.points.length > 0 ? (
                chartData.points.map((pt, i) => (
                  <span key={i} className={i === chartData.points.length - 1 ? "font-semibold text-[#c084fc]" : ""}>
                    {pt.label}
                  </span>
                ))
              ) : (
                <>
                  <span>Day 1</span>
                  <span>Day 2</span>
                  <span>Day 3</span>
                  <span>Day 4</span>
                  <span>Day 5</span>
                  <span>Day 6</span>
                  <span className="font-semibold text-[#c084fc]">Today</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Dynamic Connected Subsystems */}
        <div className="flex flex-col gap-4">
          {/* Messaging Platforms Card */}
          <div className="rounded-xl border border-white/[0.08] bg-[#11101a] p-4 shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
            <div className="flex items-center justify-between border-b border-white/5 pb-2.5">
              <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#646279]">
                <Radio className="h-4 w-4 text-emerald-400" />
                <span>Messaging Gateways</span>
              </h2>
              <button
                type="button"
                onClick={() => navigate("/channels")}
                className="text-[11px] font-medium text-[#c084fc] hover:underline cursor-pointer"
              >
                Manage ↗
              </button>
            </div>
            <div className="pt-3 space-y-2.5">
              {platformEntries.length > 0 ? (
                platformEntries.map(([name, plat]) => (
                  <div key={name} className="flex items-center justify-between text-xs">
                    <span className="capitalize text-[#9d9bb3]">{name} Gateway</span>
                    <span
                      className={cn(
                        "font-medium",
                        plat.state === "connected" || plat.state === "online"
                          ? "text-emerald-400"
                          : "text-zinc-500"
                      )}
                    >
                      {plat.state === "connected" ? "● Connected" : plat.state || "Configured"}
                    </span>
                  </div>
                ))
              ) : (
                <div className="py-2 text-center text-xs text-[#9d9bb3]">
                  No messaging platforms connected yet.
                </div>
              )}
            </div>
          </div>

          {/* Subsystems & Toolsets Card */}
          <div className="rounded-xl border border-white/[0.08] bg-[#11101a] p-4 shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
            <div className="flex items-center justify-between border-b border-white/5 pb-2.5">
              <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#646279]">
                <Layers className="h-4 w-4 text-[#9d72ff]" />
                <span>Subsystems & Extensions</span>
              </h2>
              <span className="rounded-full bg-[#9d72ff]/15 px-2 py-0.5 text-[10px] font-semibold text-[#c084fc]">
                {skills.length} Skills
              </span>
            </div>
            <div className="pt-3 space-y-2.5">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-[#9d9bb3]">
                  <Package className="h-3.5 w-3.5 text-[#9d72ff]" />
                  <span>Installed Skills</span>
                </span>
                <span className="font-mono font-medium text-white">{skills.length} Active</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-[#9d9bb3]">
                  <Plug className="h-3.5 w-3.5 text-[#60a5fa]" />
                  <span>Connected MCP Servers</span>
                </span>
                <span className="font-mono font-medium text-white">{mcpServers.length} Running</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-[#9d9bb3]">
                  <Cpu className="h-3.5 w-3.5 text-[#34d399]" />
                  <span>Configured Profiles</span>
                </span>
                <span className="font-mono font-medium text-white">{profile || "default"}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Section: Recent Sessions Table */}
      <div className="rounded-xl border border-white/[0.08] bg-[#11101a] shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
        <div className="flex flex-row items-center justify-between border-b border-white/5 p-4">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Activity className="h-4 w-4 text-[#9d72ff]" />
              <span>Recent Sessions & Delegations</span>
            </h2>
            <p className="text-xs text-[#9d9bb3]">
              Live history of background agent executions, discord channels, and direct commands
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/sessions")}
            className="flex items-center gap-1 text-xs font-medium text-[#c084fc] hover:underline cursor-pointer"
          >
            <span>View All Sessions</span>
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        </div>
        <div>
          <div className="divide-y divide-white/5 overflow-x-auto">
            {recentSessions.length > 0 ? (
              recentSessions.map((s) => (
                <div
                  key={s.id}
                  onClick={() => navigate(`/sessions?id=${s.id}`)}
                  className="flex cursor-pointer items-center justify-between px-6 py-3.5 transition-colors hover:bg-white/[0.02]"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-[#9d9bb3]">
                      <MessageSquare className="h-4 w-4 text-[#9d72ff]" />
                    </div>
                    <div>
                      <div className="text-xs font-medium text-white">
                        {s.title || `Session ${s.id.slice(0, 16)}`}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-[#9d9bb3]">
                        <span className="rounded bg-white/5 px-1.5 py-0.5 text-[9.5px] font-mono text-zinc-300">
                          {s.source || "interactive"}
                        </span>
                        <span>{s.message_count || 1} messages</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <span className="font-mono text-xs text-[#9d9bb3]">
                      {s.last_active ? timeAgo(s.last_active) : "Recently"}
                    </span>
                    <span className="text-zinc-600">›</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/5 text-[#9d9bb3] mb-2">
                  <MessageSquare className="h-5 w-5 text-[#9d72ff]" />
                </div>
                <div className="text-xs font-medium text-white">No sessions recorded yet</div>
                <p className="text-[11px] text-[#9d9bb3] mt-0.5 mb-3">
                  Start an interactive conversation in the terminal or messaging channels
                </p>
                <button
                  type="button"
                  onClick={() => navigate("/chat")}
                  className="rounded-lg bg-[#9d72ff] px-3.5 py-1.5 text-xs font-semibold text-white shadow-[0_2px_10px_rgba(157,114,255,0.35)] transition-all hover:bg-[#8b5cf6] cursor-pointer"
                >
                  Start New Chat
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
