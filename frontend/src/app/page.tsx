"use client";

import { useEffect, useState } from "react";
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
  type ReplayListItem,
  type ReplayEvent,
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

const SCENARIO_LANES: Array<{
  id: ScenarioLane;
  label: string;
  summary: string;
}> = [
  {
    id: "baseline",
    label: "No Blue Team",
    summary: "Red-only baseline to show uncontrolled blast radius.",
  },
  {
    id: "current",
    label: "Current Run",
    summary: "Current PPO defender behavior from latest run artifacts.",
  },
  {
    id: "enterprise",
    label: "Enterprise Hard Mode",
    summary: "Enterprise topology with identity + SaaS trust paths.",
  },
];

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

export default function Home() {
  const [log, setLog] = useState<ReplayEvent[]>([]);
  const [replayEvents, setReplayEvents] = useState<ReplayEvent[]>([]);
  const [graphTopology, setGraphTopology] = useState<ReplayTopology | null>(null);
  const [index, setIndex] = useState(0);
  const [selectedLane, setSelectedLane] = useState<ScenarioLane>("current");
  const [selectedReplayId, setSelectedReplayId] = useState<string | null>(null);
  const [replayCatalog, setReplayCatalog] = useState<ReplayListItem[]>([]);
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
            replayId = pickReplayIdForLane(replayList, "current") ?? pickPreferredReplayId(replayList);
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
          replayId = pickReplayIdForLane(replayList, selectedLane) ?? pickPreferredReplayId(replayList);
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
      } else {
        if (liveSessionId) {
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

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="mx-auto w-full max-w-7xl px-4 pt-4">
        <div className="text-2xl font-bold text-white mb-2">
          Aegis - Adaptive Cyber Defense
        </div>
        <div className="flex items-center gap-3 text-sm">
          <div className="text-green-400">● System Active</div>
          <div
            className={`rounded border px-2 py-0.5 text-xs font-semibold tracking-wide ${
              dataSource.mode === "mock"
                ? "border-amber-500 text-amber-300"
                : dataSource.mode === "connecting"
                  ? "border-sky-500 text-sky-300"
                  : "border-emerald-500 text-emerald-300"
            }`}
          >
            {dataSource.label}
          </div>
        </div>
        <div className="flex gap-4 text-xs mt-2">
          <div className="text-red-400">RED = attacker</div>
          <div className="text-blue-400">BLUE = defender</div>
        </div>
        <div className="mt-4 grid gap-2 md:grid-cols-3">
          {SCENARIO_LANES.map((lane) => {
            const isActive = selectedLane === lane.id;
            return (
              <button
                type="button"
                key={lane.id}
                onClick={() => setSelectedLane(lane.id)}
                className={`rounded-md border px-3 py-2 text-left transition ${
                  isActive
                    ? "border-blue-400 bg-blue-500/20 text-blue-100"
                    : "border-gray-700 bg-[#0b111a] text-gray-300 hover:border-gray-500"
                }`}
              >
                <div className="text-sm font-semibold">{lane.label}</div>
                <div className="mt-1 text-xs text-gray-300">{lane.summary}</div>
              </button>
            );
          })}
        </div>
        <div className="mt-2 text-xs text-gray-400">
          {selectedReplayId
            ? `Replay source: ${selectedReplayId}`
            : selectedLane === "baseline"
              ? "Replay source: synthetic baseline stream"
              : "Replay source: auto-select"}
          {selectedLane === "enterprise" &&
          selectedReplayId &&
          !replayCatalog.some(
            (item) => item.id === selectedReplayId && (item.scenarioId ?? "").startsWith("scenario_enterprise_"),
          )
            ? " (enterprise replay not found, using nearest available run)"
            : ""}
        </div>
      </div>
      <Graph events={log} topology={graphTopology} className="min-h-[calc(100vh-88px)]" />
    </main>
  );
}
