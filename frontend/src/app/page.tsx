"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Graph from "../components/Graph";
import {
  connectEventsStream,
  connectLiveStream,
  connectReplayStream,
  fetchReplayPayload,
  fetchReplayList,
  normalizeEvent,
  pickReplayIdForLane,
  pickPreferredReplayId,
  type ReplayEvent,
  type ReplayListItem,
  type ReplayTopology,
  type ScenarioLane,
} from "../lib/api";
import { events as mockEvents } from "../lib/mockEvents";

const REPLAY_INTERVAL_MS = 800;
const WS_CONNECT_TIMEOUT_MS = 2500;

type DataSourceStatus =
  | { mode: "connecting"; label: string }
  | { mode: "live-ws"; label: string }
  | { mode: "live-rest"; label: string }
  | { mode: "mock"; label: string };

type SlideId = "command" | "episodes" | "mission";

type AlertClassification =
  | "Initial Access"
  | "Execution"
  | "Lateral Movement"
  | "Data Exfiltration"
  | "Defense Evasion";

type AlertDatum = {
  label: AlertClassification;
  count: number;
  accent: string;
};

type ThreatBalance = {
  attacks: number;
  defenses: number;
  open: number;
  contained: number;
  redPercent: number;
  bluePercent: number;
};

type TrendBin = {
  label: string;
  red: number;
  blue: number;
};

type EpisodeCard = {
  id: string;
  scenario: string;
  createdAt: string;
  runId: string;
  status: "ACTIVE" | "READY" | "ARCHIVED";
};

type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

type FormattedIncident = {
  step: number;
  actor: ReplayEvent["actor"];
  target: string;
  action: string;
  narrative: string;
  riskLevel: RiskLevel;
  riskScore: number;
};

const SCENARIO_LANES: Array<{
  id: ScenarioLane;
  label: string;
  summary: string;
}> = [
  {
    id: "baseline",
    label: "No Blue Team",
    summary: "Red-only baseline to reveal uncontained blast radius.",
  },
  {
    id: "current",
    label: "Current Run",
    summary: "Latest PPO defender behavior from replay stream.",
  },
  {
    id: "enterprise",
    label: "Enterprise Hard Mode",
    summary: "Identity + SaaS trust paths with higher complexity.",
  },
];

const SLIDES: Array<{ id: SlideId; label: string; subtitle: string }> = [
  {
    id: "command",
    label: "Command Grid",
    subtitle: "Live operations",
  },
  {
    id: "episodes",
    label: "Episode Vault",
    subtitle: "Archive + timeline",
  },
  {
    id: "mission",
    label: "Mission Brief",
    subtitle: "System status",
  },
];

const ALERT_ORDER: AlertClassification[] = [
  "Initial Access",
  "Execution",
  "Lateral Movement",
  "Data Exfiltration",
  "Defense Evasion",
];

const ALERT_ACCENTS = ["#fda4af", "#fb7185", "#f43f5e", "#22d3ee", "#7dd3fc"];

function normalizedMockEvents(): ReplayEvent[] {
  return mockEvents
    .map((event, idx) => normalizeEvent(event, idx + 1))
    .filter((event): event is ReplayEvent => event !== null);
}

function baselineOnly(events: ReplayEvent[]): ReplayEvent[] {
  const redEvents = events.filter((event) => event.actor === "RED");
  if (redEvents.length === 0) return events;
  return redEvents.map((event, index) => ({ ...event, step: index + 1 }));
}

function classifyAction(action: string): AlertClassification {
  const value = action.toLowerCase();

  if (
    value.includes("phish") ||
    value.includes("credential") ||
    value.includes("scan") ||
    value.includes("login") ||
    value.includes("exploit")
  ) {
    return "Initial Access";
  }

  if (value.includes("lateral") || value.includes("pivot") || value.includes("movement")) {
    return "Lateral Movement";
  }

  if (value.includes("exfil") || value.includes("dump") || value.includes("steal")) {
    return "Data Exfiltration";
  }

  if (
    value.includes("evade") ||
    value.includes("disable") ||
    value.includes("obfus") ||
    value.includes("persist")
  ) {
    return "Defense Evasion";
  }

  return "Execution";
}

function formatReplayDate(raw: string | undefined): string {
  if (!raw) return "Unknown timestamp";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;

  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function replayStatus(index: number): EpisodeCard["status"] {
  if (index === 0) return "ACTIVE";
  if (index < 4) return "READY";
  return "ARCHIVED";
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function humanizeAction(action: string): string {
  return action
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

function scoreRisk(event: ReplayEvent): number {
  const action = event.action.toLowerCase();
  const target = event.target.toLowerCase();
  let score = event.actor === "RED" ? 50 : 30;

  if (action.includes("scan") || action.includes("enumerate") || action.includes("recon")) score += 10;
  if (action.includes("exploit") || action.includes("execute")) score += 16;
  if (action.includes("credential") || action.includes("phish")) score += 20;
  if (action.includes("lateral") || action.includes("pivot")) score += 18;
  if (action.includes("traffic_spike") || action.includes("anomaly")) score += 12;
  if (action.includes("exfil") || action.includes("dump") || action.includes("ransom")) score += 28;
  if (action.includes("isolate") || action.includes("block") || action.includes("quarantine")) score -= 14;
  if (action.includes("step_marker")) score -= 20;

  if (target.includes("engine") || target.includes("identity") || target.includes("vault")) score += 16;
  if (target.includes("db") || target.includes("core") || target.includes("gateway")) score += 12;
  if (target.startsWith("host-0")) score += 6;

  return clamp(score, 0, 100);
}

function riskLevelFromScore(score: number): RiskLevel {
  if (score <= 29) return "LOW";
  if (score <= 59) return "MEDIUM";
  if (score <= 79) return "HIGH";
  return "CRITICAL";
}

function buildNarrative(event: ReplayEvent, riskLevel: RiskLevel, riskScore: number): string {
  const action = event.action.toLowerCase();
  const actionLabel = humanizeAction(event.action);
  const actorLabel = event.actor === "RED" ? "Red-team" : "Blue-team";
  const targetLabel = event.target;

  if (action.includes("traffic_spike")) {
    return `${actorLabel} telemetry detected abnormal traffic on ${targetLabel}, indicating possible lateral movement pressure. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  if (action.includes("scan")) {
    return `${actorLabel} reconnaissance scanned ${targetLabel} to map exposed services and entry paths. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  if (action.includes("enumerate")) {
    return `${actorLabel} service enumeration profiled ${targetLabel} to identify exploitable interfaces. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  if (action.includes("isolate")) {
    return `${actorLabel} containment isolated ${targetLabel} from connected systems to limit adversary spread. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  if (action.includes("monitor")) {
    return `${actorLabel} monitoring intensified observation on ${targetLabel} after suspicious signals were detected. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  if (action.includes("step_marker")) {
    return `The simulator recorded a campaign checkpoint at ${targetLabel} to preserve the current attack-defense state. This point-in-time signal is assessed as ${riskLevel} risk at ${riskScore}%.`;
  }

  return `${actorLabel} executed ${actionLabel} against ${targetLabel} as part of the active engagement sequence. This event is assessed as ${riskLevel} risk at ${riskScore}%.`;
}

function formatIncident(event: ReplayEvent): FormattedIncident {
  const riskScore = scoreRisk(event);
  const riskLevel = riskLevelFromScore(riskScore);

  return {
    step: event.step,
    actor: event.actor,
    target: event.target,
    action: event.action,
    narrative: buildNarrative(event, riskLevel, riskScore),
    riskLevel,
    riskScore,
  };
}

export default function Home() {
  const [log, setLog] = useState<ReplayEvent[]>([]);
  const [replayEvents, setReplayEvents] = useState<ReplayEvent[]>([]);
  const [graphTopology, setGraphTopology] = useState<ReplayTopology | null>(null);
  const [index, setIndex] = useState(0);
  const [selectedLane, setSelectedLane] = useState<ScenarioLane>("current");
  const [selectedReplayId, setSelectedReplayId] = useState<string | null>(null);
  const [replayCatalog, setReplayCatalog] = useState<ReplayListItem[]>([]);
  const [activeSlide, setActiveSlide] = useState<SlideId>("command");
  const [dataSource, setDataSource] = useState<DataSourceStatus>({
    mode: "connecting",
    label: "CONNECTING",
  });

  useEffect(() => {
    let cancelled = false;
    let didFallback = false;
    let timeoutId: number | undefined;
    let streamConnection: { close: () => void } | null = null;

    const loadReplaySource = async (replayId: string | null) => {
      try {
        const payload = await fetchReplayPayload({ replayId: replayId ?? undefined });
        if (payload.events.length > 0) {
          const fromRunsArtifacts = Boolean(replayId && replayId.includes("__"));
          const baselineEvents =
            selectedLane === "baseline" ? baselineOnly(payload.events) : payload.events;
          return {
            events: baselineEvents,
            topology: payload.topology,
            source: {
              mode: "live-rest",
              label:
                selectedLane === "baseline"
                  ? "NO BLUE (SIMULATED)"
                  : fromRunsArtifacts
                    ? "LIVE DATA (RUNS)"
                    : "LIVE DATA (REST)",
            } as DataSourceStatus,
          };
        }
      } catch {
        // Intentional: use mock fallback below.
      }

      const fallback = normalizedMockEvents();
      return {
        events: selectedLane === "baseline" ? baselineOnly(fallback) : fallback,
        topology: null,
        source: {
          mode: "mock",
          label: selectedLane === "baseline" ? "NO BLUE (SIMULATED)" : "MOCK FALLBACK",
        } as DataSourceStatus,
      };
    };

    const startReplayFromRest = async (replayId: string | null) => {
      const replaySource = await loadReplaySource(replayId);
      if (cancelled) return;

      setLog([]);
      setIndex(0);
      setReplayEvents(replaySource.events);
      setGraphTopology(replaySource.topology);
      setDataSource(replaySource.source);
    };

    const triggerFallback = (replayId: string | null) => {
      if (cancelled || didFallback) return;
      didFallback = true;
      streamConnection?.close();
      void startReplayFromRest(replayId);
    };

    const init = async () => {
      if (selectedLane === "baseline") {
        let replayId: string | null = process.env.NEXT_PUBLIC_REPLAY_ID ?? null;
        if (!replayId) {
          try {
            const replayList = await fetchReplayList();
            setReplayCatalog(replayList);
            replayId =
              pickReplayIdForLane(replayList, "current") ?? pickPreferredReplayId(replayList);
          } catch {
            setReplayCatalog([]);
            replayId = null;
          }
        }
        setSelectedReplayId(replayId);
        await startReplayFromRest(replayId);
        return;
      }

      setDataSource({ mode: "connecting", label: "CONNECTING" });
      let replayId: string | null = process.env.NEXT_PUBLIC_REPLAY_ID ?? null;

      if (!replayId) {
        try {
          const replayList = await fetchReplayList();
          setReplayCatalog(replayList);
          replayId =
            pickReplayIdForLane(replayList, selectedLane) ?? pickPreferredReplayId(replayList);
        } catch {
          setReplayCatalog([]);
          replayId = null;
        }
      }
      setSelectedReplayId(replayId);

      if (cancelled) return;

      const liveSessionId = process.env.NEXT_PUBLIC_LIVE_SESSION_ID;
      const liveWsLabel = replayId
        ? "LIVE DATA (REPLAY WS)"
        : liveSessionId
          ? "LIVE DATA (SESSION WS)"
          : "LIVE DATA (WS)";

      const onOpen = () => {
        if (cancelled) return;
        if (timeoutId !== undefined) {
          window.clearTimeout(timeoutId);
          timeoutId = undefined;
        }
        setLog([]);
        setIndex(0);
        setReplayEvents([]);
        setGraphTopology(null);
        setDataSource({ mode: "live-ws", label: liveWsLabel });
      };

      const onEvent = (event: ReplayEvent) => {
        if (cancelled) return;
        setLog((prev) => [...prev, event]);
      };

      const onError = () => {
        triggerFallback(replayId);
      };
      const onClose = () => {
        triggerFallback(replayId);
      };

      if (replayId) {
        streamConnection = connectReplayStream(replayId, {
          onOpen,
          onEvent,
          onError,
          onClose,
        });
      } else if (liveSessionId) {
        streamConnection = connectLiveStream(liveSessionId, {
          onOpen,
          onEvent,
          onError,
          onClose,
        });
      } else {
        streamConnection = connectEventsStream({
          onOpen,
          onEvent,
          onError,
          onClose,
        });
      }

      timeoutId = window.setTimeout(() => {
        triggerFallback(replayId);
      }, WS_CONNECT_TIMEOUT_MS);
    };

    void init();

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
      streamConnection?.close();
    };
  }, [selectedLane]);

  useEffect(() => {
    if (index >= replayEvents.length) return;

    const timer = window.setTimeout(() => {
      setLog((prev) => [...prev, replayEvents[index]]);
      setIndex((prev) => prev + 1);
    }, REPLAY_INTERVAL_MS);

    return () => window.clearTimeout(timer);
  }, [index, replayEvents]);

  const fallbackEvents = useMemo(() => normalizedMockEvents(), []);
  const telemetry = log.length > 0 ? log : replayEvents;
  const events = telemetry.length > 0 ? telemetry : fallbackEvents;

  const alertData = useMemo<AlertDatum[]>(() => {
    const counts: Record<AlertClassification, number> = {
      "Initial Access": 0,
      Execution: 0,
      "Lateral Movement": 0,
      "Data Exfiltration": 0,
      "Defense Evasion": 0,
    };

    events.forEach((event) => {
      counts[classifyAction(event.action)] += 1;
    });

    return ALERT_ORDER.map((label, idx) => ({
      label,
      count: counts[label],
      accent: ALERT_ACCENTS[idx],
    }));
  }, [events]);

  const threatBalance = useMemo<ThreatBalance>(() => {
    const attacks = events.filter((event) => event.actor === "RED").length;
    const defenses = events.filter((event) => event.actor === "BLUE").length;
    const open = Math.max(attacks - defenses, 0);
    const contained = Math.min(attacks, defenses);

    const total = attacks + defenses;
    const redPercent = total === 0 ? 0 : Math.round((attacks / total) * 100);
    const bluePercent = total === 0 ? 0 : Math.round((defenses / total) * 100);

    return {
      attacks,
      defenses,
      open,
      contained,
      redPercent,
      bluePercent,
    };
  }, [events]);

  const trendBins = useMemo<TrendBin[]>(() => {
    const labels = ["-55m", "-50m", "-45m", "-40m", "-35m", "-30m", "-25m", "-20m", "-15m", "-10m", "-5m", "Now"];
    const bins = labels.map((label) => ({ label, red: 0, blue: 0 }));

    events.forEach((event, idx) => {
      const bucket = idx % bins.length;
      if (event.actor === "RED") bins[bucket].red += 1;
      if (event.actor === "BLUE") bins[bucket].blue += 1;
    });

    return bins;
  }, [events]);

  const hotTargets = useMemo(() => {
    const score: Record<string, number> = {};
    events.forEach((event) => {
      score[event.target] = (score[event.target] ?? 0) + (event.actor === "RED" ? 2 : 1);
    });

    return Object.entries(score)
      .map(([target, value]) => ({ target, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);
  }, [events]);

  const episodes = useMemo<EpisodeCard[]>(() => {
    const catalogItems = replayCatalog.map((item, idx) => ({
      id: item.id,
      scenario: item.scenarioId ?? "scenario_unknown",
      createdAt: formatReplayDate(item.createdAt),
      runId: item.runId ?? "n/a",
      status: replayStatus(idx),
    }));

    if (catalogItems.length > 0) return catalogItems;

    return [
      {
        id: selectedReplayId ?? "local-fallback",
        scenario:
          selectedLane === "enterprise"
            ? "scenario_enterprise_hard"
            : selectedLane === "baseline"
              ? "scenario_baseline"
              : "scenario_current_run",
        createdAt: "Current session",
        runId: "local",
        status: "ACTIVE",
      },
    ];
  }, [replayCatalog, selectedReplayId, selectedLane]);

  const logFeed = useMemo(() => events.slice(-100).reverse(), [events]);
  const formattedLogFeed = useMemo(
    () => logFeed.map((event) => formatIncident(event)),
    [logFeed],
  );

  const statusTone =
    dataSource.mode === "mock"
      ? "border-amber-500/70 text-amber-200 bg-amber-500/10"
      : dataSource.mode === "connecting"
        ? "border-cyan-500/70 text-cyan-100 bg-cyan-500/10"
        : "border-emerald-500/70 text-emerald-100 bg-emerald-500/10";

  return (
    <main className="relative min-h-screen overflow-hidden px-4 pb-10 pt-6 text-[#f4f4f5] md:px-8">
      <div className="aegis-mesh" aria-hidden />
      <div className="aegis-grid" aria-hidden />

      <div className="relative z-10 mx-auto w-full max-w-[1500px]">
        <header className="aegis-card px-4 py-4 md:px-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <ShieldLogo />
              <div>
                <h1 className="font-display text-2xl tracking-[0.35em] text-[#fecaca]">AEGIS</h1>
                <p className="text-xs uppercase tracking-[0.2em] text-[#fda4af]">
                  Adaptive cyber defense command center
                </p>
              </div>
            </div>

            <nav className="flex flex-wrap items-center gap-2">
              {SLIDES.map((slide) => {
                const active = activeSlide === slide.id;
                return (
                  <button
                    key={slide.id}
                    type="button"
                    onClick={() => setActiveSlide(slide.id)}
                    className={`rounded-md border px-3 py-2 text-left transition ${
                      active
                        ? "border-red-300 bg-red-500/20 text-red-50 shadow-[0_0_18px_rgba(248,113,113,0.35)]"
                        : "border-red-500/35 bg-black/35 text-red-200 hover:border-red-300/70"
                    }`}
                  >
                    <div className="font-display text-xs uppercase tracking-[0.16em]">{slide.label}</div>
                    <div className="text-[10px] uppercase tracking-[0.14em] text-red-200/80">{slide.subtitle}</div>
                  </button>
                );
              })}
            </nav>

            <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em]">
              <span className={`rounded-md border px-3 py-1 font-semibold ${statusTone}`}>{dataSource.label}</span>
              <span className="rounded-md border border-red-500/40 bg-black/35 px-3 py-1 text-red-100">
                Replay {selectedReplayId ?? "auto"}
              </span>
            </div>
          </div>

          <div className="mt-4 grid gap-2 md:grid-cols-3">
            {SCENARIO_LANES.map((lane) => {
              const isActive = selectedLane === lane.id;
              return (
                <button
                  type="button"
                  key={lane.id}
                  onClick={() => setSelectedLane(lane.id)}
                  className={`rounded-lg border px-3 py-3 text-left transition ${
                    isActive
                      ? "border-cyan-300/70 bg-cyan-400/15 text-cyan-50"
                      : "border-red-500/30 bg-black/25 text-red-100 hover:border-red-300/70"
                  }`}
                >
                  <div className="font-display text-sm uppercase tracking-[0.14em]">{lane.label}</div>
                  <div className="mt-1 text-xs text-red-100/80">{lane.summary}</div>
                </button>
              );
            })}
          </div>
        </header>

        <section className="mt-5">
          {activeSlide === "command" ? (
            <CommandSlide
              alertData={alertData}
              threatBalance={threatBalance}
              logFeed={formattedLogFeed}
              hotTargets={hotTargets}
              graphTopology={graphTopology}
              graphEvents={log}
            />
          ) : null}

          {activeSlide === "episodes" ? (
            <EpisodesSlide episodes={episodes} trendBins={trendBins} logFeed={formattedLogFeed} />
          ) : null}

          {activeSlide === "mission" ? (
            <MissionSlide
              threatBalance={threatBalance}
              selectedLane={selectedLane}
              dataSource={dataSource}
              replayId={selectedReplayId}
            />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function CommandSlide({
  alertData,
  threatBalance,
  logFeed,
  hotTargets,
  graphTopology,
  graphEvents,
}: {
  alertData: AlertDatum[];
  threatBalance: ThreatBalance;
  logFeed: FormattedIncident[];
  hotTargets: Array<{ target: string; value: number }>;
  graphTopology: ReplayTopology | null;
  graphEvents: ReplayEvent[];
}) {
  const threatStatusRef = useRef<HTMLElement | null>(null);
  const liveLogRef = useRef<HTMLElement | null>(null);
  const [desktopThreatHeight, setDesktopThreatHeight] = useState<number | null>(null);

  const maxAlert = Math.max(...alertData.map((item) => item.count), 1);
  const totalAlerts = alertData.reduce((sum, item) => sum + item.count, 0);
  const dominantAlert = alertData.reduce(
    (best, item) => (item.count > best.count ? item : best),
    alertData[0],
  );
  const dominantShare = totalAlerts > 0 ? Math.round((dominantAlert.count / totalAlerts) * 100) : 0;

  useEffect(() => {
    if (typeof window === "undefined") return;
    const threatEl = threatStatusRef.current;
    if (!threatEl) return;

    const sync = () => {
      if (window.innerWidth < 1280) {
        setDesktopThreatHeight(null);
        return;
      }
      const nextHeight = Math.ceil(threatEl.getBoundingClientRect().height);
      setDesktopThreatHeight(nextHeight > 0 ? nextHeight : null);
    };

    sync();

    const observer = new ResizeObserver(() => {
      sync();
    });
    observer.observe(threatEl);
    window.addEventListener("resize", sync);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", sync);
    };
  }, []);

  return (
    <div className="grid gap-5 xl:grid-cols-12">
      <article className="aegis-card p-4 xl:col-span-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">
            Open Alerts by Classification
          </h2>
          <span className="rounded border border-red-400/50 px-2 py-1 text-[10px] uppercase tracking-[0.15em] text-red-200">
            Live
          </span>
        </div>

        <div className="mt-4 text-[11px] text-red-100/80">
          {totalAlerts > 0 ? (
            <span>
              Dominant signal: <span className="font-semibold text-red-100">{dominantAlert.label}</span> with{" "}
              <span className="font-semibold text-red-100">{dominantAlert.count}</span> events (
              {dominantShare}%). Current open pressure remains {threatBalance.open} incidents.
            </span>
          ) : (
            <span>
              Waiting for incoming telemetry. Classification bars remain visible and will update as soon as
              events arrive.
            </span>
          )}
        </div>

        <div className="mt-4 flex h-56 items-end gap-2 rounded-lg border border-red-500/25 bg-black/30 p-3">
          {alertData.map((item) => {
            const sharePct = totalAlerts > 0 ? Math.round((item.count / totalAlerts) * 100) : 0;
            const fillPct = item.count > 0 ? Math.max((item.count / maxAlert) * 100, 14) : 0;
            return (
              <div key={item.label} className="flex flex-1 flex-col items-center gap-2">
                <div className="relative h-36 w-full rounded-md border border-white/10 bg-[#070a13]">
                  <div className="absolute inset-x-2 bottom-2 top-2 rounded-sm border border-red-500/15 bg-black/30" />
                  <div
                    className="absolute inset-x-3 bottom-3 rounded-sm"
                    style={{
                      height: `${fillPct}%`,
                      backgroundImage: `linear-gradient(to top, rgba(3,7,18,0.78), ${item.accent})`,
                      opacity: item.count > 0 ? 0.95 : 0.35,
                    }}
                  />
                </div>
                <span className="text-center text-[10px] uppercase tracking-[0.12em] text-red-100/80">
                  {item.label}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-red-200/90">
                  {item.count} · {sharePct}%
                </span>
              </div>
            );
          })}
        </div>
      </article>

      <article className="xl:col-span-8">
        <Graph
          events={graphEvents}
          topology={graphTopology}
          className="h-[520px]"
        />
      </article>

      <article ref={threatStatusRef} className="aegis-card p-4 xl:col-span-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">Threat Status</h2>
          <span className="text-xs uppercase tracking-[0.12em] text-red-100/80">Blue vs Red</span>
        </div>

        <div className="mt-4 rounded-lg border border-red-500/30 bg-black/35 p-3">
          <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.14em] text-red-100/85">
            <span>Attack Pressure</span>
            <span>{threatBalance.redPercent}%</span>
          </div>
          <div className="h-4 overflow-hidden rounded-full border border-red-600/40 bg-[#14080d]">
            <div
              className="h-full bg-gradient-to-r from-red-800 via-red-500 to-red-300"
              style={{ width: `${Math.max(threatBalance.redPercent, 2)}%` }}
            />
          </div>

          <div className="mb-2 mt-4 flex items-center justify-between text-[11px] uppercase tracking-[0.14em] text-cyan-100/85">
            <span>Containment Pressure</span>
            <span>{threatBalance.bluePercent}%</span>
          </div>
          <div className="h-4 overflow-hidden rounded-full border border-cyan-600/40 bg-[#05111a]">
            <div
              className="h-full bg-gradient-to-r from-cyan-900 via-cyan-500 to-cyan-200"
              style={{ width: `${Math.max(threatBalance.bluePercent, 2)}%` }}
            />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <MiniMetric label="Open incidents" value={threatBalance.open} tone="text-red-200" />
          <MiniMetric label="Contained" value={threatBalance.contained} tone="text-cyan-200" />
          <MiniMetric label="RED actions" value={threatBalance.attacks} tone="text-red-300" />
          <MiniMetric label="BLUE actions" value={threatBalance.defenses} tone="text-cyan-300" />
        </div>

        <div className="mt-4 rounded-lg border border-red-500/25 bg-black/30 p-3">
          <div className="text-[11px] uppercase tracking-[0.16em] text-red-100/80">Hot targets</div>
          <ul className="mt-2 space-y-1 text-xs">
            {hotTargets.map((target) => (
              <li key={target.target} className="flex items-center justify-between text-red-50/90">
                <span>{target.target}</span>
                <span className="font-semibold text-red-300">{target.value}</span>
              </li>
            ))}
          </ul>
        </div>
      </article>

      <article
        ref={liveLogRef}
        className="aegis-card p-4 xl:col-span-8 flex min-h-[440px] flex-col overflow-hidden"
        style={desktopThreatHeight ? { height: `${desktopThreatHeight}px` } : undefined}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">Live Tactical Log</h2>
          <span className="text-[11px] uppercase tracking-[0.12em] text-red-100/80">
            Auto-updating stream
          </span>
        </div>

        <div className="min-h-[260px] flex-1 overflow-y-auto rounded-lg border border-red-500/25 bg-black/40 p-2">
          {logFeed.map((event) => (
            <div
              key={`${event.step}-${event.target}-${event.action}-${event.riskScore}`}
              className="mb-2 grid gap-2 rounded-md border border-white/8 bg-black/30 px-2 py-2 text-xs md:grid-cols-[68px_72px_minmax(0,1fr)_150px_130px]"
            >
              <span className="font-mono text-red-100/80">#{event.step.toString().padStart(3, "0")}</span>
              <span
                className={`rounded px-2 py-0.5 text-center font-semibold ${
                  event.actor === "RED"
                    ? "bg-red-500/20 text-red-100 border border-red-400/40"
                    : "bg-cyan-500/20 text-cyan-100 border border-cyan-400/40"
                }`}
              >
                {event.actor}
              </span>
              <span className="text-red-50/95">{event.narrative}</span>
              <span className="truncate text-red-200/80">{event.target}</span>
              <RiskBadge level={event.riskLevel} score={event.riskScore} />
            </div>
          ))}
        </div>
      </article>
    </div>
  );
}

function EpisodesSlide({
  episodes,
  trendBins,
  logFeed,
}: {
  episodes: EpisodeCard[];
  trendBins: TrendBin[];
  logFeed: FormattedIncident[];
}) {
  const maxBinValue = Math.max(
    ...trendBins.map((bin) => Math.max(bin.red, bin.blue)),
    1,
  );

  return (
    <div className="grid gap-5 xl:grid-cols-12">
      <article className="aegis-card p-4 xl:col-span-5">
        <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">Episode History</h2>
        <div className="mt-3 h-[320px] space-y-2 overflow-auto pr-1">
          {episodes.map((episode) => (
            <div
              key={episode.id}
              className="rounded-lg border border-red-500/25 bg-black/30 p-3 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-sm tracking-[0.12em] text-red-100">{episode.id}</span>
                <span
                  className={`rounded border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] ${
                    episode.status === "ACTIVE"
                      ? "border-cyan-300/60 bg-cyan-400/15 text-cyan-100"
                      : episode.status === "READY"
                        ? "border-red-300/60 bg-red-400/15 text-red-100"
                        : "border-zinc-400/60 bg-zinc-700/20 text-zinc-200"
                  }`}
                >
                  {episode.status}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-red-100/80">
                <span>Scenario: {episode.scenario}</span>
                <span>Run: {episode.runId}</span>
                <span className="col-span-2">Created: {episode.createdAt}</span>
              </div>
            </div>
          ))}
        </div>
      </article>

      <article className="aegis-card p-4 xl:col-span-7">
        <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">
          Historic Attack/Defense Trend
        </h2>
        <div className="mt-4 grid h-[320px] grid-cols-12 items-end gap-2 rounded-lg border border-red-500/20 bg-black/35 p-4">
          {trendBins.map((bin) => {
            const redHeight = Math.max((bin.red / maxBinValue) * 100, bin.red > 0 ? 10 : 4);
            const blueHeight = Math.max((bin.blue / maxBinValue) * 100, bin.blue > 0 ? 10 : 4);

            return (
              <div key={bin.label} className="flex h-full flex-col items-center justify-end gap-2">
                <div className="relative flex h-[78%] w-full items-end justify-center gap-1">
                  <div
                    className="w-2 rounded-t bg-gradient-to-t from-red-900 to-red-300"
                    style={{ height: `${redHeight}%` }}
                  />
                  <div
                    className="w-2 rounded-t bg-gradient-to-t from-cyan-900 to-cyan-300"
                    style={{ height: `${blueHeight}%` }}
                  />
                </div>
                <span className="text-[10px] uppercase tracking-[0.08em] text-red-100/70">{bin.label}</span>
              </div>
            );
          })}
        </div>
      </article>

      <article className="aegis-card p-4 xl:col-span-12 flex min-h-[500px] flex-col">
        <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">Complete Incident Chronicle</h2>
        <div className="mt-3 min-h-[300px] flex-1 overflow-auto rounded-lg border border-red-500/20 bg-black/35">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[#0c0f19] text-red-200">
              <tr>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.12em]">Step</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.12em]">Actor</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.12em]">Narrative</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.12em]">Target</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.12em]">Risk</th>
              </tr>
            </thead>
            <tbody>
              {logFeed.map((event) => (
                <tr key={`${event.step}-${event.target}-${event.action}-${event.riskScore}`} className="border-t border-white/8 align-top">
                  <td className="px-3 py-2 font-mono text-red-100/80">{event.step}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 ${
                        event.actor === "RED"
                          ? "bg-red-500/20 text-red-100"
                          : "bg-cyan-500/20 text-cyan-100"
                      }`}
                    >
                      {event.actor}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-red-50/95">{event.narrative}</td>
                  <td className="px-3 py-2 text-red-200/80">{event.target}</td>
                  <td className="px-3 py-2">
                    <RiskBadge level={event.riskLevel} score={event.riskScore} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}

function MissionSlide({
  threatBalance,
  selectedLane,
  dataSource,
  replayId,
}: {
  threatBalance: ThreatBalance;
  selectedLane: ScenarioLane;
  dataSource: DataSourceStatus;
  replayId: string | null;
}) {
  const missionProgress = Math.min(100, Math.max(15, 35 + threatBalance.contained * 3));
  const systemHealth = Math.max(22, 82 - threatBalance.open * 2);

  return (
    <div className="grid gap-5 xl:grid-cols-12">
      <article className="aegis-card p-5 xl:col-span-7">
        <h2 className="font-display text-lg uppercase tracking-[0.22em] text-[#fecaca]">Mission Narrative</h2>
        <p className="mt-3 text-sm leading-relaxed text-red-50/90">
          AEGIS is a reinforcement-learning cyber defense interface built to show how adaptive blue-team
          policies react against evolving red-team tactics in real time. The command grid translates raw
          attack telemetry into judge-friendly visuals, while retaining technical depth for security teams.
        </p>

        <div className="mt-5 space-y-3">
          <MissionItem
            title="Phase 1: Detect"
            description="Classify adversary behavior across initial access, execution, movement, and exfiltration."
          />
          <MissionItem
            title="Phase 2: Contain"
            description="Deploy adaptive defender controls and isolate compromised assets before blast radius expands."
          />
          <MissionItem
            title="Phase 3: Recover"
            description="Stabilize operations, archive each episode, and produce mission-ready replay evidence."
          />
        </div>
      </article>

      <article className="aegis-card p-5 xl:col-span-5">
        <h2 className="font-display text-sm uppercase tracking-[0.22em] text-[#fecaca]">System Status</h2>

        <div className="mt-4 space-y-3 text-xs">
          <StatusRow label="Source" value={dataSource.label} />
          <StatusRow label="Scenario lane" value={selectedLane} />
          <StatusRow label="Replay id" value={replayId ?? "auto-select"} />
        </div>

        <div className="mt-4 rounded-lg border border-red-500/25 bg-black/30 p-3">
          <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-[0.14em] text-red-100/80">
            <span>Mission completion</span>
            <span>{missionProgress}%</span>
          </div>
          <ProgressBar value={missionProgress} tone="red" />

          <div className="mb-1 mt-4 flex items-center justify-between text-[11px] uppercase tracking-[0.14em] text-cyan-100/80">
            <span>System health</span>
            <span>{systemHealth}%</span>
          </div>
          <ProgressBar value={systemHealth} tone="cyan" />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <MiniMetric label="Open incidents" value={threatBalance.open} tone="text-red-200" />
          <MiniMetric label="Contained" value={threatBalance.contained} tone="text-cyan-200" />
          <MiniMetric label="Red pressure" value={`${threatBalance.redPercent}%`} tone="text-red-300" />
          <MiniMetric label="Blue pressure" value={`${threatBalance.bluePercent}%`} tone="text-cyan-300" />
        </div>
      </article>
    </div>
  );
}

function ShieldLogo() {
  return (
    <div className="relative h-11 w-11 overflow-hidden rounded-md border border-red-400/50 bg-black/40">
      <svg viewBox="0 0 128 128" className="h-full w-full">
        <defs>
          <linearGradient id="shieldGradient" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="#fca5a5" />
            <stop offset="55%" stopColor="#ef4444" />
            <stop offset="100%" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
        <path
          d="M64 12 18 28v31c0 32 22 50 46 57 24-7 46-25 46-57V28L64 12Z"
          fill="url(#shieldGradient)"
          opacity="0.95"
        />
        <path
          d="M64 27 33 38v21c0 22 14 35 31 41 17-6 31-19 31-41V38L64 27Z"
          fill="#06080f"
          opacity="0.78"
        />
        <path d="M64 35 46 43v16h18V35Z" fill="#f43f5e" opacity="0.9" />
        <path d="M64 59H46c1 14 8 24 18 29V59Z" fill="#22d3ee" opacity="0.9" />
        <path d="M64 35v24h18V43l-18-8Z" fill="#fb7185" opacity="0.9" />
      </svg>
    </div>
  );
}

function riskToneClass(level: RiskLevel): string {
  if (level === "LOW") return "border-cyan-400/60 bg-cyan-500/15 text-cyan-100";
  if (level === "MEDIUM") return "border-yellow-400/60 bg-yellow-500/15 text-yellow-100";
  if (level === "HIGH") return "border-orange-400/60 bg-orange-500/20 text-orange-100";
  return "border-red-400/65 bg-red-500/20 text-red-100";
}

function RiskBadge({
  level,
  score,
}: {
  level: RiskLevel;
  score: number;
}) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] ${riskToneClass(level)}`}
    >
      {level} · {score}%
    </span>
  );
}

function MiniMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <div className="rounded-md border border-red-500/25 bg-black/25 px-2 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-red-100/70">{label}</div>
      <div className={`font-display mt-1 text-base ${tone}`}>{value}</div>
    </div>
  );
}

function StatusRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between border-b border-white/10 pb-1">
      <span className="uppercase tracking-[0.14em] text-red-100/75">{label}</span>
      <span className="text-right text-red-50">{value}</span>
    </div>
  );
}

function ProgressBar({
  value,
  tone,
}: {
  value: number;
  tone: "red" | "cyan";
}) {
  return (
    <div className={`h-3 overflow-hidden rounded-full border ${tone === "red" ? "border-red-600/40 bg-red-950/40" : "border-cyan-600/40 bg-cyan-950/35"}`}>
      <div
        className={`h-full ${
          tone === "red"
            ? "bg-gradient-to-r from-red-900 via-red-500 to-red-300"
            : "bg-gradient-to-r from-cyan-900 via-cyan-500 to-cyan-200"
        }`}
        style={{ width: `${Math.max(4, value)}%` }}
      />
    </div>
  );
}

function MissionItem({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-red-500/25 bg-black/25 p-3">
      <div className="font-display text-sm uppercase tracking-[0.14em] text-red-100">{title}</div>
      <div className="mt-1 text-xs leading-relaxed text-red-50/85">{description}</div>
    </div>
  );
}
