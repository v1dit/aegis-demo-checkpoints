"use client";

import { useEffect, useState } from "react";
import Graph from "../components/Graph";
import {
  connectEventsStream,
  connectLiveStream,
  connectReplayStream,
  fetchEvents,
  fetchReplayList,
  normalizeEvent,
  pickPreferredReplayId,
  type ReplayEvent,
} from "../lib/api";
import { events as mockEvents } from "../lib/mockEvents";

const REPLAY_INTERVAL_MS = 800;
const WS_CONNECT_TIMEOUT_MS = 2500;

type DataSourceStatus =
  | { mode: "connecting"; label: string }
  | { mode: "live-ws"; label: string }
  | { mode: "live-rest"; label: string }
  | { mode: "mock"; label: string };

function normalizedMockEvents(): ReplayEvent[] {
  return mockEvents
    .map((event, idx) => normalizeEvent(event, idx + 1))
    .filter((event): event is ReplayEvent => event !== null);
}

export default function Home() {
  const [log, setLog] = useState<ReplayEvent[]>([]);
  const [replayEvents, setReplayEvents] = useState<ReplayEvent[]>([]);
  const [index, setIndex] = useState(0);
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
        const fetched = await fetchEvents({ replayId: replayId ?? undefined });
        if (fetched.length > 0) {
          const fromRunsArtifacts = Boolean(replayId && replayId.includes("__"));
          return {
            events: fetched,
            source: {
              mode: "live-rest",
              label: fromRunsArtifacts ? "LIVE DATA (RUNS)" : "LIVE DATA (REST)",
            } as DataSourceStatus,
          };
        }
      } catch {
        // Intentional: use mock fallback below.
      }

      return {
        events: normalizedMockEvents(),
        source: { mode: "mock", label: "MOCK FALLBACK" } as DataSourceStatus,
      };
    };

    const startReplayFromRest = async (replayId: string | null) => {
      const replaySource = await loadReplaySource(replayId);
      if (cancelled) return;

      setLog([]);
      setIndex(0);
      setReplayEvents(replaySource.events);
      setDataSource(replaySource.source);
    };

    const triggerFallback = (replayId: string | null) => {
      if (cancelled || didFallback) return;
      didFallback = true;
      streamConnection?.close();
      void startReplayFromRest(replayId);
    };

    const init = async () => {
      setDataSource({ mode: "connecting", label: "CONNECTING" });
      let replayId: string | null = process.env.NEXT_PUBLIC_REPLAY_ID ?? null;

      if (!replayId) {
        try {
          const replayList = await fetchReplayList();
          replayId = pickPreferredReplayId(replayList);
        } catch {
          replayId = null;
        }
      }

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
  }, []);

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
      </div>
      <Graph events={log} className="min-h-[calc(100vh-88px)]" />
    </main>
  );
}
