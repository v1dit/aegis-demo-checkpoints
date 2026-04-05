"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import Graph from "../components/Graph";
import {
  cancelSandboxRun,
  connectLiveRunStream,
  connectEventsStream,
  connectLiveStream,
  connectReplayStream,
  createSandboxRun,
  fetchSandboxCatalog,
  fetchSandboxRunStatus,
  fetchReplayPayload,
  fetchReplayList,
  normalizeEvent,
  pickReplayIdForLane,
  pickPreferredReplayId,
  type EpisodeSpec,
  type SandboxCatalogResponse,
  type SandboxRunLifecycle,
  type SandboxRunStatus,
  type ReplayEvent,
  type ReplayListItem,
  type ReplayTopology,
  type ScenarioLane,
} from "../lib/api";
import {
  classifyAction,
  formatIncident,
  type AlertClassification,
  type FormattedIncident,
  type RiskLevel,
} from "../lib/incidents";
import { events as mockEvents } from "../lib/mockEvents";

const REPLAY_INTERVAL_MS = 800;
const WS_CONNECT_TIMEOUT_MS = 2500;
const SANDBOX_STATUS_POLL_MS = 3000;

type DashboardLane = ScenarioLane | "sandbox";

type DataSourceStatus =
  | { mode: "connecting"; label: string }
  | { mode: "live-ws"; label: string }
  | { mode: "live-rest"; label: string }
  | { mode: "mock"; label: string };

type SlideId = "command" | "episodes" | "mission";

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

type ReplaySpeed = 1 | 2 | 5 | 10;

type SandboxUiState =
  | "idle"
  | "validating"
  | "submitting"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

const SCENARIO_LANES: Array<{
  id: DashboardLane;
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
  {
    id: "sandbox",
    label: "Sandbox Live",
    summary: "Build and run a custom live episode against the deployed model backend.",
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

const SANDBOX_TERMINAL_STATUSES: SandboxRunLifecycle[] = [
  "completed",
  "failed",
  "cancelled",
];

function isSandboxTerminal(status: SandboxRunLifecycle | null | undefined): boolean {
  if (!status) return false;
  return SANDBOX_TERMINAL_STATUSES.includes(status);
}

function asSandboxUiState(status: SandboxRunLifecycle): SandboxUiState {
  return status;
}

function createDefaultEpisodeSpec(): EpisodeSpec {
  return {
    name: "Live Sandbox Drill",
    seed: 4242,
    horizon: 120,
    nodes: [
      { id: "workstation-1", role: "endpoint", os: "windows" },
      { id: "db-1", role: "database", os: "linux" },
    ],
    vulnerabilities: [{ id: "cve-2025-10001", node_id: "workstation-1", severity: "high" }],
    red_objectives: [{ id: "obj-exfiltrate-db", type: "data_exfiltration", target: "db-1" }],
    defender_mode: "aegis",
  };
}

function validateEpisodeSpec(spec: EpisodeSpec): string[] {
  const errors: string[] = [];

  if (!spec.name.trim()) errors.push("Episode name is required.");
  if (!Number.isFinite(spec.horizon) || spec.horizon < 1 || spec.horizon > 10000) {
    errors.push("Horizon must be between 1 and 10,000.");
  }

  if (!Array.isArray(spec.nodes) || spec.nodes.length < 1) {
    errors.push("At least one node is required.");
  }

  if (!Array.isArray(spec.red_objectives) || spec.red_objectives.length < 1) {
    errors.push("At least one red objective is required.");
  }

  const nodeIds = new Set<string>();
  for (const node of spec.nodes) {
    if (!node.id.trim()) {
      errors.push("Each node needs an id.");
      continue;
    }
    if (nodeIds.has(node.id)) {
      errors.push(`Duplicate node id: ${node.id}`);
    }
    nodeIds.add(node.id);
  }

  for (const vuln of spec.vulnerabilities) {
    if (!vuln.id.trim()) errors.push("Each vulnerability needs an id.");
    if (!nodeIds.has(vuln.node_id)) {
      errors.push(`Vulnerability node reference is invalid: ${vuln.node_id}`);
    }
  }

  for (const objective of spec.red_objectives) {
    if (!objective.id.trim()) errors.push("Each objective needs an id.");
    if (!objective.type.trim()) errors.push("Each objective needs a type.");
    if (!nodeIds.has(objective.target)) {
      errors.push(`Objective target is invalid: ${objective.target}`);
    }
  }

  if (spec.defender_mode !== "aegis") {
    errors.push('Defender mode must be "aegis".');
  }

  return errors;
}


export default function Home() {
  const [log, setLog] = useState<ReplayEvent[]>([]);
  const [replayEvents, setReplayEvents] = useState<ReplayEvent[]>([]);
  const [graphTopology, setGraphTopology] = useState<ReplayTopology | null>(null);
  const [index, setIndex] = useState(0);
  const [isReplayPlaying, setIsReplayPlaying] = useState(true);
  const [replaySpeed, setReplaySpeed] = useState<ReplaySpeed>(1);
  const [selectedLane, setSelectedLane] = useState<DashboardLane>("current");
  const [selectedReplayId, setSelectedReplayId] = useState<string | null>(null);
  const [replayCatalog, setReplayCatalog] = useState<ReplayListItem[]>([]);
  const [activeSlide, setActiveSlide] = useState<SlideId>("command");
  const [dataSource, setDataSource] = useState<DataSourceStatus>({
    mode: "connecting",
    label: "CONNECTING",
  });
  const [globalNotice, setGlobalNotice] = useState<string | null>(null);

  const [sandboxForm, setSandboxForm] = useState<EpisodeSpec>(createDefaultEpisodeSpec);
  const [sandboxCatalog, setSandboxCatalog] = useState<SandboxCatalogResponse | null>(null);
  const [sandboxCatalogStatus, setSandboxCatalogStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [sandboxFieldErrors, setSandboxFieldErrors] = useState<string[]>([]);
  const [sandboxUiState, setSandboxUiState] = useState<SandboxUiState>("idle");
  const [sandboxRunId, setSandboxRunId] = useState<string | null>(null);
  const [sandboxStreamUrl, setSandboxStreamUrl] = useState<string | null>(null);
  const [sandboxStatus, setSandboxStatus] = useState<SandboxRunStatus | null>(null);
  const [sandboxMetrics, setSandboxMetrics] = useState<Record<string, number | string | null>>({});
  const [sandboxUnavailable, setSandboxUnavailable] = useState<string | null>(null);

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
      if (selectedLane === "sandbox") {
        setLog([]);
        setReplayEvents([]);
        setIndex(0);
        setSelectedReplayId(null);
        setDataSource({ mode: "connecting", label: "SANDBOX READY" });
        return;
      }

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
            pickReplayIdForLane(replayList, selectedLane as ScenarioLane) ??
            pickPreferredReplayId(replayList);
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
    if (selectedLane !== "sandbox") return;
    if (sandboxCatalogStatus === "ready" || sandboxCatalogStatus === "loading") return;

    let cancelled = false;

    void fetchSandboxCatalog()
      .then((catalog) => {
        if (cancelled) return;
        setSandboxCatalog(catalog);
        setSandboxCatalogStatus("ready");
      })
      .catch((error) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Sandbox catalog is unavailable.";
        setSandboxCatalogStatus("error");
        setSandboxUnavailable(message);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedLane, sandboxCatalogStatus]);

  const retrySandboxBackend = async () => {
    setSandboxUnavailable(null);
    setSandboxCatalogStatus("loading");
    try {
      const catalog = await fetchSandboxCatalog();
      setSandboxCatalog(catalog);
      setSandboxCatalogStatus("ready");
      setGlobalNotice(null);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sandbox backend unavailable.";
      setSandboxCatalogStatus("error");
      setSandboxUnavailable(message);
      setGlobalNotice("Sandbox backend retry failed. Falling back to replay mode.");
      setSelectedLane("current");
      return false;
    }
  };

  const submitSandboxRun = async () => {
    setSandboxFieldErrors([]);
    setSandboxUiState("validating");
    const errors = validateEpisodeSpec(sandboxForm);
    if (errors.length > 0) {
      setSandboxFieldErrors(errors);
      setSandboxUiState("idle");
      return;
    }

    setSandboxUiState("submitting");
    setSandboxUnavailable(null);

    try {
      const created = await createSandboxRun(sandboxForm);
      setSandboxRunId(created.run_id);
      setSandboxStreamUrl(created.stream_url);
      setSandboxUiState(asSandboxUiState(created.status));
      setSandboxStatus({
        run_id: created.run_id,
        status: created.status,
      });
      setSandboxMetrics({});
      setLog([]);
      setReplayEvents([]);
      setIndex(0);
      setDataSource({ mode: "connecting", label: "SANDBOX QUEUED" });
      setGlobalNotice(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to submit sandbox run.";
      setSandboxUiState("failed");
      setSandboxUnavailable(message);
    }
  };

  const requestSandboxCancel = async () => {
    if (!sandboxRunId) return;
    try {
      const response = await cancelSandboxRun(sandboxRunId);
      setSandboxStatus(response);
      setSandboxUiState(asSandboxUiState(response.status));
      setDataSource({ mode: "live-rest", label: "SANDBOX CANCELLED" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Cancel request failed.";
      setSandboxUnavailable(message);
    }
  };

  useEffect(() => {
    if (selectedLane !== "sandbox") return;
    if (!sandboxRunId) return;
    if (!(sandboxUiState === "queued" || sandboxUiState === "running")) return;

    let cancelled = false;
    let reconnectTimerId: number | undefined;
    const pollTimerId = window.setInterval(() => {
      void syncStatus();
    }, SANDBOX_STATUS_POLL_MS);
    let reconnectAttempt = 0;
    let connection: { close: () => void } | null = null;

    const applyStatus = (status: SandboxRunStatus) => {
      if (cancelled) return;
      setSandboxStatus(status);
      if (status.kpis) {
        setSandboxMetrics((prev) => ({ ...prev, ...status.kpis }));
      }
      const nextUiState = asSandboxUiState(status.status);
      setSandboxUiState(nextUiState);

      if (status.status === "running") {
        setDataSource({ mode: "live-ws", label: "SANDBOX LIVE" });
      } else if (status.status === "queued") {
        setDataSource({ mode: "connecting", label: "SANDBOX QUEUED" });
      } else {
        setDataSource({ mode: "live-rest", label: `SANDBOX ${status.status.toUpperCase()}` });
      }
    };

    const syncStatus = async () => {
      try {
        const status = await fetchSandboxRunStatus(sandboxRunId);
        applyStatus(status);
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Failed to refresh sandbox status.";
        setSandboxUnavailable(message);
      }
    };

    const scheduleReconnect = () => {
      if (cancelled || isSandboxTerminal(sandboxUiState)) return;
      const backoffMs = Math.min(6000, 800 * Math.pow(1.7, reconnectAttempt));
      reconnectAttempt += 1;
      reconnectTimerId = window.setTimeout(() => {
        if (cancelled) return;
        openConnection();
      }, backoffMs);
    };

    const openConnection = () => {
      connection?.close();
      connection = connectLiveRunStream(sandboxRunId, {
        onOpen: () => {
          if (cancelled) return;
          reconnectAttempt = 0;
          setDataSource({ mode: "live-ws", label: "SANDBOX LIVE" });
          setSandboxUnavailable(null);
        },
        onAction: (event) => {
          if (cancelled) return;
          setLog((prev) => [...prev, event]);
        },
        onMetric: (payload) => {
          if (cancelled) return;
          const kpis = payload.kpis;
          if (kpis && typeof kpis === "object" && !Array.isArray(kpis)) {
            setSandboxMetrics((prev) => ({ ...prev, ...(kpis as Record<string, number | string>) }));
            return;
          }
          const metricRecord: Record<string, string | number | null> = {};
          Object.entries(payload).forEach(([key, value]) => {
            if (typeof value === "number" || typeof value === "string") {
              metricRecord[key] = value;
            }
          });
          if (Object.keys(metricRecord).length > 0) {
            setSandboxMetrics((prev) => ({ ...prev, ...metricRecord }));
          }
        },
        onMarker: (payload) => {
          const markerStatus =
            typeof payload.status === "string"
              ? (payload.status as SandboxRunLifecycle)
              : null;
          if (markerStatus) {
            setSandboxUiState(asSandboxUiState(markerStatus));
          }
          void syncStatus();
        },
        onUnknownType: (messageType) => {
          console.warn(`Ignored unknown live stream type: ${messageType}`);
        },
        onError: () => {
          scheduleReconnect();
        },
        onClose: () => {
          scheduleReconnect();
        },
      });
    };

    openConnection();
    void syncStatus();

    return () => {
      cancelled = true;
      window.clearInterval(pollTimerId);
      if (reconnectTimerId !== undefined) {
        window.clearTimeout(reconnectTimerId);
      }
      connection?.close();
    };
  }, [selectedLane, sandboxRunId, sandboxUiState]);

  useEffect(() => {
    if (selectedLane === "sandbox") return;
    if (!isReplayPlaying) return;
    if (index >= replayEvents.length) return;

    const interval = Math.max(80, Math.floor(REPLAY_INTERVAL_MS / replaySpeed));

    const timer = window.setTimeout(() => {
      setLog((prev) => [...prev, replayEvents[index]]);
      setIndex((prev) => prev + 1);
    }, interval);

    return () => window.clearTimeout(timer);
  }, [index, replayEvents, selectedLane, isReplayPlaying, replaySpeed]);

  const fallbackEvents = useMemo(() => normalizedMockEvents(), []);
  const telemetry = log.length > 0 ? log : replayEvents;
  const events =
    selectedLane === "sandbox"
      ? telemetry
      : telemetry.length > 0
        ? telemetry
        : fallbackEvents;

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

  const replayControlsEnabled = selectedLane !== "sandbox" && replayEvents.length > 0;
  const canReplayStep = replayControlsEnabled && index < replayEvents.length;

  const replayPauseToggle = () => {
    if (!replayControlsEnabled) return;
    setIsReplayPlaying((prev) => !prev);
  };

  const replayStepForward = () => {
    if (!canReplayStep) return;
    setLog((prev) => [...prev, replayEvents[index]]);
    setIndex((prev) => prev + 1);
  };

  const replayRestart = () => {
    if (!replayControlsEnabled) return;
    setLog([]);
    setIndex(0);
    setIsReplayPlaying(true);
  };

  const setNodeField = (row: number, field: "id" | "role" | "os", value: string) => {
    setSandboxForm((prev) => {
      const next = [...prev.nodes];
      next[row] = { ...next[row], [field]: value };
      return { ...prev, nodes: next };
    });
  };

  const setVulnerabilityField = (
    row: number,
    field: "id" | "node_id" | "severity",
    value: string,
  ) => {
    setSandboxForm((prev) => {
      const next = [...prev.vulnerabilities];
      next[row] = { ...next[row], [field]: value };
      return { ...prev, vulnerabilities: next };
    });
  };

  const setObjectiveField = (row: number, field: "id" | "type" | "target", value: string) => {
    setSandboxForm((prev) => {
      const next = [...prev.red_objectives];
      next[row] = { ...next[row], [field]: value };
      return { ...prev, red_objectives: next };
    });
  };

  const sandboxCanCancel =
    sandboxUiState === "queued" || sandboxUiState === "running";
  const sandboxTimeline = selectedLane === "sandbox" ? formattedLogFeed : [];

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
                {selectedLane === "sandbox"
                  ? `Run ${sandboxRunId ?? "pending"}`
                  : `Replay ${selectedReplayId ?? "auto"}`}
              </span>
            </div>
          </div>

          {globalNotice ? (
            <div className="mt-3 rounded-md border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
              {globalNotice}
            </div>
          ) : null}

          <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
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
            <>
              {selectedLane === "sandbox" ? (
                <SandboxLanePanel
                  form={sandboxForm}
                  setForm={setSandboxForm}
                  catalog={sandboxCatalog}
                  catalogStatus={sandboxCatalogStatus}
                  fieldErrors={sandboxFieldErrors}
                  uiState={sandboxUiState}
                  runId={sandboxRunId}
                  streamUrl={sandboxStreamUrl}
                  status={sandboxStatus}
                  metrics={sandboxMetrics}
                  unavailableMessage={sandboxUnavailable}
                  onRetryBackend={retrySandboxBackend}
                  onSubmitRun={submitSandboxRun}
                  onCancelRun={requestSandboxCancel}
                  canCancel={sandboxCanCancel}
                  timeline={sandboxTimeline}
                  setNodeField={setNodeField}
                  setVulnerabilityField={setVulnerabilityField}
                  setObjectiveField={setObjectiveField}
                />
              ) : null}

              <CommandSlide
                alertData={alertData}
                threatBalance={threatBalance}
                logFeed={formattedLogFeed}
                hotTargets={hotTargets}
                graphTopology={graphTopology}
                graphEvents={log}
              />
            </>
          ) : null}

          {activeSlide === "episodes" ? (
            <EpisodesSlide
              episodes={episodes}
              trendBins={trendBins}
              logFeed={formattedLogFeed}
              replayControlsEnabled={replayControlsEnabled}
              isReplayPlaying={isReplayPlaying}
              replaySpeed={replaySpeed}
              replayProgress={index}
              replayTotal={replayEvents.length}
              canStep={canReplayStep}
              onTogglePlay={replayPauseToggle}
              onStep={replayStepForward}
              onRestart={replayRestart}
              onSpeedChange={setReplaySpeed}
            />
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

function SandboxLanePanel({
  form,
  setForm,
  catalog,
  catalogStatus,
  fieldErrors,
  uiState,
  runId,
  streamUrl,
  status,
  metrics,
  unavailableMessage,
  onRetryBackend,
  onSubmitRun,
  onCancelRun,
  canCancel,
  timeline,
  setNodeField,
  setVulnerabilityField,
  setObjectiveField,
}: {
  form: EpisodeSpec;
  setForm: Dispatch<SetStateAction<EpisodeSpec>>;
  catalog: SandboxCatalogResponse | null;
  catalogStatus: "idle" | "loading" | "ready" | "error";
  fieldErrors: string[];
  uiState: SandboxUiState;
  runId: string | null;
  streamUrl: string | null;
  status: SandboxRunStatus | null;
  metrics: Record<string, number | string | null>;
  unavailableMessage: string | null;
  onRetryBackend: () => Promise<boolean>;
  onSubmitRun: () => Promise<void>;
  onCancelRun: () => Promise<void>;
  canCancel: boolean;
  timeline: FormattedIncident[];
  setNodeField: (row: number, field: "id" | "role" | "os", value: string) => void;
  setVulnerabilityField: (
    row: number,
    field: "id" | "node_id" | "severity",
    value: string,
  ) => void;
  setObjectiveField: (row: number, field: "id" | "type" | "target", value: string) => void;
}) {
  const statusLabel = uiState.toUpperCase();
  const terminal = status ? isSandboxTerminal(status.status) : false;
  const metricEntries = Object.entries(metrics).slice(0, 8);
  const objectiveTemplates = catalog?.objective_templates ?? [];
  const vulnerabilityTemplates = catalog?.vulnerability_templates ?? [];
  const nodeTemplates = catalog?.node_templates ?? [];

  return (
    <article className="aegis-card mb-5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">
          Sandbox Live Control Plane
        </h2>
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-md border border-cyan-400/60 bg-cyan-500/10 px-2 py-1 uppercase tracking-[0.12em] text-cyan-100">
            {statusLabel}
          </span>
          <span className="rounded-md border border-red-500/50 bg-black/40 px-2 py-1 uppercase tracking-[0.12em] text-red-100">
            {runId ? `run ${runId}` : "no active run"}
          </span>
        </div>
      </div>

      {catalogStatus === "loading" ? (
        <div className="mt-3 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
          Loading sandbox catalog...
        </div>
      ) : null}

      {unavailableMessage ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          <span>Sandbox backend unavailable: {unavailableMessage}</span>
          <button
            type="button"
            onClick={() => {
              void onRetryBackend();
            }}
            className="rounded border border-amber-300/60 bg-amber-400/20 px-2 py-1 uppercase tracking-[0.12em] text-amber-50"
          >
            Retry Backend
          </button>
        </div>
      ) : null}

      {fieldErrors.length > 0 ? (
        <div className="mt-3 rounded-md border border-red-500/60 bg-red-500/10 px-3 py-2 text-xs text-red-100">
          {fieldErrors.map((error) => (
            <div key={error}>• {error}</div>
          ))}
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
            <div className="grid gap-2 md:grid-cols-3">
              <LabeledInput
                label="Name"
                value={form.name}
                onChange={(value) => setForm((prev) => ({ ...prev, name: value }))}
              />
              <LabeledInput
                label="Seed"
                value={String(form.seed ?? "")}
                onChange={(value) =>
                  setForm((prev) => ({
                    ...prev,
                    seed: value.trim() ? Number.parseInt(value, 10) : undefined,
                  }))
                }
              />
              <LabeledInput
                label="Horizon"
                value={String(form.horizon)}
                onChange={(value) =>
                  setForm((prev) => ({
                    ...prev,
                    horizon: Number.parseInt(value, 10) || 0,
                  }))
                }
              />
            </div>

            <BuilderSection
              title="Nodes"
              onAdd={() =>
                setForm((prev) => ({
                  ...prev,
                  nodes: [...prev.nodes, { id: `host-${prev.nodes.length + 1}`, role: "endpoint", os: "linux" }],
                }))
              }
            >
              {form.nodes.map((node, idx) => (
                <div key={`${node.id}-${idx}`} className="grid gap-2 md:grid-cols-4">
                  <LabeledInput
                    label="Node ID"
                    value={node.id}
                    onChange={(value) => setNodeField(idx, "id", value)}
                  />
                  <LabeledInput
                    label="Role"
                    value={node.role ?? ""}
                    onChange={(value) => setNodeField(idx, "role", value)}
                    listId={`node-role-${idx}`}
                    listValues={nodeTemplates.map((template) => template.role)}
                  />
                  <LabeledInput
                    label="OS"
                    value={node.os ?? ""}
                    onChange={(value) => setNodeField(idx, "os", value)}
                    listId={`node-os-${idx}`}
                    listValues={["windows", "linux", "macos"]}
                  />
                  <ActionCell
                    onRemove={() =>
                      setForm((prev) => ({
                        ...prev,
                        nodes: prev.nodes.filter((_, row) => row !== idx),
                      }))
                    }
                    disabled={form.nodes.length <= 1}
                  />
                </div>
              ))}
            </BuilderSection>

            <BuilderSection
              title="Vulnerabilities"
              onAdd={() =>
                setForm((prev) => ({
                  ...prev,
                  vulnerabilities: [
                    ...prev.vulnerabilities,
                    {
                      id: vulnerabilityTemplates[0]?.id ?? `cve-${Date.now()}`,
                      node_id: prev.nodes[0]?.id ?? "",
                      severity: "medium",
                    },
                  ],
                }))
              }
            >
              {form.vulnerabilities.map((vulnerability, idx) => (
                <div key={`${vulnerability.id}-${idx}`} className="grid gap-2 md:grid-cols-4">
                  <LabeledInput
                    label="Vuln ID"
                    value={vulnerability.id}
                    onChange={(value) => setVulnerabilityField(idx, "id", value)}
                    listId={`vuln-id-${idx}`}
                    listValues={vulnerabilityTemplates.map((template) => template.id)}
                  />
                  <LabeledInput
                    label="Node ID"
                    value={vulnerability.node_id}
                    onChange={(value) => setVulnerabilityField(idx, "node_id", value)}
                    listId={`vuln-node-${idx}`}
                    listValues={form.nodes.map((node) => node.id)}
                  />
                  <LabeledInput
                    label="Severity"
                    value={vulnerability.severity ?? "medium"}
                    onChange={(value) => setVulnerabilityField(idx, "severity", value)}
                    listId={`vuln-severity-${idx}`}
                    listValues={["low", "medium", "high"]}
                  />
                  <ActionCell
                    onRemove={() =>
                      setForm((prev) => ({
                        ...prev,
                        vulnerabilities: prev.vulnerabilities.filter((_, row) => row !== idx),
                      }))
                    }
                  />
                </div>
              ))}
            </BuilderSection>

            <BuilderSection
              title="Red Objectives"
              onAdd={() =>
                setForm((prev) => ({
                  ...prev,
                  red_objectives: [
                    ...prev.red_objectives,
                    {
                      id: `obj-${prev.red_objectives.length + 1}`,
                      type: objectiveTemplates[0]?.type ?? "data_exfiltration",
                      target: prev.nodes[0]?.id ?? "",
                    },
                  ],
                }))
              }
            >
              {form.red_objectives.map((objective, idx) => (
                <div key={`${objective.id}-${idx}`} className="grid gap-2 md:grid-cols-4">
                  <LabeledInput
                    label="Objective ID"
                    value={objective.id}
                    onChange={(value) => setObjectiveField(idx, "id", value)}
                  />
                  <LabeledInput
                    label="Type"
                    value={objective.type}
                    onChange={(value) => setObjectiveField(idx, "type", value)}
                    listId={`obj-type-${idx}`}
                    listValues={objectiveTemplates.map((template) => template.type)}
                  />
                  <LabeledInput
                    label="Target"
                    value={objective.target}
                    onChange={(value) => setObjectiveField(idx, "target", value)}
                    listId={`obj-target-${idx}`}
                    listValues={form.nodes.map((node) => node.id)}
                  />
                  <ActionCell
                    onRemove={() =>
                      setForm((prev) => ({
                        ...prev,
                        red_objectives: prev.red_objectives.filter((_, row) => row !== idx),
                      }))
                    }
                    disabled={form.red_objectives.length <= 1}
                  />
                </div>
              ))}
            </BuilderSection>

            <div className="mt-3 rounded-md border border-red-500/20 bg-black/45 p-2">
              <div className="mb-2 text-[11px] uppercase tracking-[0.12em] text-red-200/80">EpisodeSpec Preview</div>
              <pre className="max-h-44 overflow-auto text-[10px] text-red-100/85">
                {JSON.stringify(form, null, 2)}
              </pre>
            </div>
          </div>
        </div>

        <div className="space-y-3 xl:col-span-5">
          <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
            <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-red-200/80">Run Controls</div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  void onSubmitRun();
                }}
                disabled={uiState === "submitting" || uiState === "queued" || uiState === "running"}
                className="rounded border border-emerald-300/60 bg-emerald-500/15 px-3 py-1 text-xs uppercase tracking-[0.12em] text-emerald-100 disabled:opacity-50"
              >
                Run Live
              </button>
              <button
                type="button"
                onClick={() => {
                  void onCancelRun();
                }}
                disabled={!canCancel}
                className="rounded border border-red-300/60 bg-red-500/15 px-3 py-1 text-xs uppercase tracking-[0.12em] text-red-100 disabled:opacity-50"
              >
                Cancel Run
              </button>
            </div>
            <div className="mt-2 text-[11px] text-red-100/80">
              {streamUrl ? `Stream: ${streamUrl}` : "Stream URL appears after run creation."}
            </div>
          </div>

          <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
            <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-red-200/80">Live Metrics Panel</div>
            {metricEntries.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {metricEntries.map(([key, value]) => (
                  <MiniMetric key={key} label={key.replaceAll("_", " ")} value={String(value)} tone="text-cyan-200" />
                ))}
              </div>
            ) : (
              <p className="text-xs text-red-100/70">Metrics will appear when the run starts producing data.</p>
            )}
          </div>

          <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
            <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-red-200/80">Run Timeline</div>
            <div className="max-h-52 space-y-2 overflow-auto pr-1">
              {timeline.length > 0 ? (
                timeline.slice(0, 12).map((event) => (
                  <div key={`${event.step}-${event.action}-${event.target}`} className="rounded border border-white/10 bg-black/35 px-2 py-2 text-[11px] text-red-50/90">
                    <div className="font-mono text-red-200/80">#{event.step}</div>
                    <div>{event.narrative}</div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-red-100/70">Waiting for first live events...</p>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
            <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-red-200/80">Run Terminal Summary</div>
            {terminal && status ? (
              <div className="space-y-1 text-xs text-red-50/90">
                <div>Status: {status.status.toUpperCase()}</div>
                <div>Started: {status.started_at ?? "n/a"}</div>
                <div>Ended: {status.ended_at ?? "n/a"}</div>
                <div>
                  Error: {status.error?.message ?? (status.status === "failed" ? "Unknown failure" : "none")}
                </div>
              </div>
            ) : (
              <div className="text-xs text-red-100/70">Run is in progress. Terminal summary appears when finished.</div>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function BuilderSection({
  title,
  onAdd,
  children,
}: {
  title: string;
  onAdd: () => void;
  children: ReactNode;
}) {
  return (
    <div className="mt-3 rounded-md border border-red-500/20 bg-black/35 p-2">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.12em] text-red-200/80">{title}</div>
        <button
          type="button"
          onClick={onAdd}
          className="rounded border border-cyan-400/60 bg-cyan-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-cyan-100"
        >
          Add
        </button>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  listId,
  listValues,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  listId?: string;
  listValues?: string[];
}) {
  return (
    <label className="block text-[11px]">
      <span className="mb-1 block uppercase tracking-[0.12em] text-red-200/80">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        list={listId}
        className="w-full rounded border border-red-500/30 bg-black/55 px-2 py-1 text-xs text-red-50 focus:border-cyan-300/60 focus:outline-none"
      />
      {listId && listValues && listValues.length > 0 ? (
        <datalist id={listId}>
          {listValues.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
      ) : null}
    </label>
  );
}

function ActionCell({
  onRemove,
  disabled,
}: {
  onRemove: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-end">
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        className="w-full rounded border border-red-400/60 bg-red-500/10 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-red-100 disabled:opacity-40"
      >
        Remove
      </button>
    </div>
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
  replayControlsEnabled,
  isReplayPlaying,
  replaySpeed,
  replayProgress,
  replayTotal,
  canStep,
  onTogglePlay,
  onStep,
  onRestart,
  onSpeedChange,
}: {
  episodes: EpisodeCard[];
  trendBins: TrendBin[];
  logFeed: FormattedIncident[];
  replayControlsEnabled: boolean;
  isReplayPlaying: boolean;
  replaySpeed: ReplaySpeed;
  replayProgress: number;
  replayTotal: number;
  canStep: boolean;
  onTogglePlay: () => void;
  onStep: () => void;
  onRestart: () => void;
  onSpeedChange: (speed: ReplaySpeed) => void;
}) {
  const maxBinValue = Math.max(
    ...trendBins.map((bin) => Math.max(bin.red, bin.blue)),
    1,
  );

  return (
    <div className="grid gap-5 xl:grid-cols-12">
      <article className="aegis-card p-4 xl:col-span-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-sm uppercase tracking-[0.2em] text-[#fecaca]">
            Replay Transport Controls
          </h2>
          <div className="text-xs text-red-100/80">
            Progress {Math.min(replayProgress, replayTotal)} / {replayTotal}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={!replayControlsEnabled}
            className="rounded border border-cyan-400/60 bg-cyan-500/10 px-3 py-1 text-xs uppercase tracking-[0.12em] text-cyan-100 disabled:opacity-50"
          >
            {isReplayPlaying ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            onClick={onStep}
            disabled={!replayControlsEnabled || !canStep}
            className="rounded border border-red-400/60 bg-red-500/10 px-3 py-1 text-xs uppercase tracking-[0.12em] text-red-100 disabled:opacity-50"
          >
            Step
          </button>
          <button
            type="button"
            onClick={onRestart}
            disabled={!replayControlsEnabled}
            className="rounded border border-red-400/60 bg-black/30 px-3 py-1 text-xs uppercase tracking-[0.12em] text-red-100 disabled:opacity-50"
          >
            Restart
          </button>
          {[1, 2, 5, 10].map((speed) => (
            <button
              type="button"
              key={speed}
              onClick={() => onSpeedChange(speed as ReplaySpeed)}
              disabled={!replayControlsEnabled}
              className={`rounded border px-3 py-1 text-xs uppercase tracking-[0.12em] disabled:opacity-50 ${
                replaySpeed === speed
                  ? "border-emerald-300/70 bg-emerald-500/20 text-emerald-100"
                  : "border-red-500/35 bg-black/30 text-red-100"
              }`}
            >
              {speed}x
            </button>
          ))}
          {!replayControlsEnabled ? (
            <span className="text-xs text-red-100/65">
              Controls activate when replay payload mode is active.
            </span>
          ) : null}
        </div>
      </article>

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
  selectedLane: DashboardLane;
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
