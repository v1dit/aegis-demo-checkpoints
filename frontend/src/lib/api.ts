export type Actor = "RED" | "BLUE";

export type ReplayEvent = {
  step: number;
  actor: Actor;
  action: string;
  target: string;
};

export type ReplayListItem = {
  id: string;
  runId?: string;
  createdAt?: string;
  raw: unknown;
};

type StreamHandlers = {
  onEvent: (event: ReplayEvent) => void;
  onOpen?: () => void;
  onError?: (error: Event | Error) => void;
  onClose?: (event: CloseEvent) => void;
};

type StreamConnection = {
  close: () => void;
};

type EventFetchOptions = {
  replayId?: string;
  signal?: AbortSignal;
};

type EpisodeStitchState = {
  activeEpisodeKey: string | null;
  episodeOffset: number;
  lastEpisodeStep: number;
  lastGlobalStep: number;
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_REST_EVENTS_PATH = "/events";
const DEFAULT_WS_EVENTS_PATH = "/ws/events";
const DEFAULT_REPLAY_LIST_PATH = "/replay/list";
const DEFAULT_REPLAY_BUNDLE_PATH_TEMPLATE = "/replay/{id}/bundle";
const DEFAULT_WS_REPLAY_PATH_TEMPLATE = "/stream/replay/{id}";
const DEFAULT_WS_LIVE_PATH_TEMPLATE = "/stream/live/{session_id}";
const LOCAL_REPLAY_LIST_PATH = "/api/local/replay/list";
const LOCAL_REPLAY_BUNDLE_PATH_TEMPLATE = "/api/local/replay/{id}/bundle";

function normalizePath(path: string): string {
  if (!path) return "/";
  return path.startsWith("/") ? path : `/${path}`;
}

function replacePathParam(template: string, paramName: string, value: string): string {
  return template.replace(`{${paramName}}`, encodeURIComponent(value));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function toNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function toStep(value: unknown, fallbackStep: number): number {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return Math.floor(value);
  }

  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed >= 0) {
      return parsed;
    }
  }

  return fallbackStep;
}

function toActor(value: unknown): Actor | null {
  const normalized = toNonEmptyString(value)?.toUpperCase();
  if (!normalized) return null;

  if (
    normalized === "RED" ||
    normalized === "ATTACKER" ||
    normalized === "ADVERSARY" ||
    normalized === "OFFENSE" ||
    normalized === "OFFENSIVE"
  ) {
    return "RED";
  }

  if (
    normalized === "BLUE" ||
    normalized === "DEFENDER" ||
    normalized === "DEFENCE" ||
    normalized === "DEFENSE" ||
    normalized === "SOC"
  ) {
    return "BLUE";
  }

  return null;
}

function inferActor(action: string): Actor {
  const actionLower = action.toLowerCase();

  if (
    actionLower.includes("isolate") ||
    actionLower.includes("monitor") ||
    actionLower.includes("detect") ||
    actionLower.includes("block") ||
    actionLower.includes("defend")
  ) {
    return "BLUE";
  }

  return "RED";
}

function normalizeTargetId(rawTarget: string): string {
  const target = rawTarget.trim();
  if (!target) return target;

  // Normalize host_1 / host-1 / host01 / host_01 => host-01
  const hostMatch = /^host[-_]?(\d{1,2})$/i.exec(target);
  if (hostMatch) {
    const index = Number.parseInt(hostMatch[1], 10);
    if (Number.isFinite(index)) {
      return `host-${String(index).padStart(2, "0")}`;
    }
  }

  return target;
}

function resolveApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

function resolveUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }

  const base = resolveApiBaseUrl();
  return new URL(normalizePath(pathOrUrl), base).toString();
}

function resolveWsUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith("ws://") || pathOrUrl.startsWith("wss://")) {
    return pathOrUrl;
  }

  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    const parsed = new URL(pathOrUrl);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    return parsed.toString();
  }

  const base = new URL(resolveApiBaseUrl());
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${base.host}${normalizePath(pathOrUrl)}`;
}

function resolveRestEventsUrl(): string {
  const configured = process.env.NEXT_PUBLIC_EVENTS_REST_PATH ?? DEFAULT_REST_EVENTS_PATH;
  return resolveUrl(configured);
}

function resolveReplayListUrl(): string {
  const configured = process.env.NEXT_PUBLIC_REPLAY_LIST_PATH ?? DEFAULT_REPLAY_LIST_PATH;
  return resolveUrl(configured);
}

function resolveReplayBundleUrl(replayId: string): string {
  const template =
    process.env.NEXT_PUBLIC_REPLAY_BUNDLE_PATH_TEMPLATE ??
    DEFAULT_REPLAY_BUNDLE_PATH_TEMPLATE;
  return resolveUrl(replacePathParam(template, "id", replayId));
}

function resolveReplayStreamUrl(replayId: string): string {
  const template =
    process.env.NEXT_PUBLIC_EVENTS_WS_REPLAY_PATH_TEMPLATE ??
    DEFAULT_WS_REPLAY_PATH_TEMPLATE;
  return resolveWsUrl(replacePathParam(template, "id", replayId));
}

function resolveLiveStreamUrl(sessionId: string): string {
  const template =
    process.env.NEXT_PUBLIC_EVENTS_WS_LIVE_PATH_TEMPLATE ??
    DEFAULT_WS_LIVE_PATH_TEMPLATE;
  return resolveWsUrl(replacePathParam(template, "session_id", sessionId));
}

function resolveDefaultEventsStreamUrl(): string {
  const configured = process.env.NEXT_PUBLIC_EVENTS_WS_PATH ?? DEFAULT_WS_EVENTS_PATH;
  return resolveWsUrl(configured);
}

function resolveLocalReplayListUrl(): string {
  return LOCAL_REPLAY_LIST_PATH;
}

function resolveLocalReplayBundleUrl(replayId: string): string {
  return replacePathParam(LOCAL_REPLAY_BUNDLE_PATH_TEMPLATE, "id", replayId);
}

export function normalizeEvent(
  rawEvent: unknown,
  fallbackStep: number,
): ReplayEvent | null {
  const event = asRecord(rawEvent);
  if (!event) return null;

  const action =
    toNonEmptyString(event.action) ??
    toNonEmptyString(event.action_type) ??
    toNonEmptyString(event.event_type) ??
    toNonEmptyString(event.signal) ??
    "unknown_action";

  const target =
    normalizeTargetId(
      toNonEmptyString(event.target) ??
        toNonEmptyString(event.target_host) ??
        toNonEmptyString(event.host) ??
        toNonEmptyString(event.node_id) ??
        toNonEmptyString(event.target_node) ??
        "unknown_target",
    );

  const actor =
    toActor(event.actor) ??
    toActor(event.detector) ??
    toActor(event.team) ??
    toActor(event.side) ??
    inferActor(action);

  const step = toStep(
    event.step ?? event.seq ?? event.sequence ?? event.index,
    fallbackStep,
  );

  return { step, actor, action, target };
}

function extractRawEvents(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;

  const record = asRecord(payload);
  if (!record) return [];

  if (Array.isArray(record.events)) return record.events;
  if (Array.isArray(record.data)) return record.data;
  if (Array.isArray(record.results)) return record.results;

  const embeddedEvent = asRecord(record.event);
  if (embeddedEvent) return [embeddedEvent];

  return [payload];
}

function extractEpisodeKey(rawEvent: unknown): string | null {
  const event = asRecord(rawEvent);
  if (!event) return null;

  const directEpisode =
    toNonEmptyString(event.episode_id) ??
    toNonEmptyString(event.episodeId) ??
    toNonEmptyString(event.episode) ??
    toNonEmptyString(event.trajectory_id);

  if (directEpisode) return directEpisode;

  const runId = toNonEmptyString(event.run_id) ?? toNonEmptyString(event.runId);
  const replayId =
    toNonEmptyString(event.replay_id) ?? toNonEmptyString(event.replayId);

  if (runId && replayId) return `${runId}:${replayId}`;
  return runId ?? replayId ?? null;
}

function createEpisodeStitchState(): EpisodeStitchState {
  return {
    activeEpisodeKey: null,
    episodeOffset: 0,
    lastEpisodeStep: 0,
    lastGlobalStep: 0,
  };
}

function stitchEventStep(
  event: ReplayEvent,
  rawEvent: unknown,
  state: EpisodeStitchState,
): ReplayEvent {
  const episodeKey = extractEpisodeKey(rawEvent);

  if (state.activeEpisodeKey === null) {
    state.activeEpisodeKey = episodeKey ?? "default";
  }

  const switchedEpisode =
    episodeKey !== null &&
    state.activeEpisodeKey !== null &&
    episodeKey !== state.activeEpisodeKey;

  const impliedBoundary =
    episodeKey === null &&
    state.lastEpisodeStep > 0 &&
    event.step <= state.lastEpisodeStep;

  if (switchedEpisode || impliedBoundary) {
    state.episodeOffset = state.lastGlobalStep;
    state.lastEpisodeStep = 0;
    if (episodeKey) {
      state.activeEpisodeKey = episodeKey;
    }
  }

  let withinEpisodeStep = event.step;
  if (withinEpisodeStep <= 0) {
    withinEpisodeStep = state.lastEpisodeStep + 1;
  }

  if (withinEpisodeStep <= state.lastEpisodeStep) {
    withinEpisodeStep = state.lastEpisodeStep + 1;
  }

  state.lastEpisodeStep = withinEpisodeStep;

  let globalStep = state.episodeOffset + withinEpisodeStep;
  if (globalStep <= state.lastGlobalStep) {
    globalStep = state.lastGlobalStep + 1;
  }

  state.lastGlobalStep = globalStep;

  return {
    ...event,
    step: globalStep,
  };
}

function normalizeEvents(
  rawEvents: unknown[],
  stitchState = createEpisodeStitchState(),
): ReplayEvent[] {
  const normalized = rawEvents
    .map((event, idx) => normalizeEvent(event, idx + 1))
    .filter((event): event is ReplayEvent => event !== null);

  return normalized.map((event, idx) => stitchEventStep(event, rawEvents[idx], stitchState));
}

function parseJsonLines(text: string): unknown[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      try {
        return JSON.parse(line) as unknown;
      } catch {
        return null;
      }
    })
    .filter((value): value is unknown => value !== null);
}

function parseReplayList(payload: unknown): ReplayListItem[] {
  const container = asRecord(payload);
  const rawList = Array.isArray(payload)
    ? payload
    : Array.isArray(container?.replays)
      ? container.replays
      : Array.isArray(container?.data)
        ? container.data
        : Array.isArray(container?.items)
          ? container.items
          : [];

  return rawList
    .map((item, idx) => {
      const record = asRecord(item);
      if (!record) return null;

      const id =
        toNonEmptyString(record.id) ??
        toNonEmptyString(record.replay_id) ??
        toNonEmptyString(record.replayId) ??
        toNonEmptyString(record.name) ??
        `replay-${idx + 1}`;

      const runId =
        toNonEmptyString(record.run_id) ??
        toNonEmptyString(record.runId) ??
        undefined;

      const createdAt =
        toNonEmptyString(record.created_at) ??
        toNonEmptyString(record.createdAt) ??
        undefined;

      return { id, runId, createdAt, raw: item };
    })
    .filter((item): item is ReplayListItem => item !== null);
}

function extractInlineEvents(bundlePayload: unknown): unknown[] {
  const bundle = asRecord(bundlePayload);
  if (!bundle) return [];

  if (Array.isArray(bundle.events)) return bundle.events;

  const replay = asRecord(bundle.replay);
  if (replay && Array.isArray(replay.events)) return replay.events;

  const data = asRecord(bundle.data);
  if (data && Array.isArray(data.events)) return data.events;

  return [];
}

function extractEventPointer(bundlePayload: unknown): string | null {
  const bundle = asRecord(bundlePayload);
  if (!bundle) return null;

  const directPointer =
    toNonEmptyString(bundle.events_jsonl_url) ??
    toNonEmptyString(bundle.events_url) ??
    toNonEmptyString(bundle.events_path) ??
    toNonEmptyString(bundle.events_jsonl);

  if (directPointer) return directPointer;

  const artifacts = asRecord(bundle.artifacts);
  if (artifacts) {
    const artifactPointer =
      toNonEmptyString(artifacts.events_jsonl_url) ??
      toNonEmptyString(artifacts.events_url) ??
      toNonEmptyString(artifacts.events_path) ??
      toNonEmptyString(artifacts.events_jsonl);

    if (artifactPointer) return artifactPointer;

    const replayArtifacts = asRecord(artifacts.replays);
    if (replayArtifacts) {
      const replayPointer =
        toNonEmptyString(replayArtifacts.events_jsonl_url) ??
        toNonEmptyString(replayArtifacts.events_url) ??
        toNonEmptyString(replayArtifacts.events_path) ??
        toNonEmptyString(replayArtifacts.events_jsonl);

      if (replayPointer) return replayPointer;
    }
  }

  const eventsAsString = toNonEmptyString(bundle.events);
  return eventsAsString ?? null;
}

async function fetchUnknownJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed request (${response.status}) for ${url}`);
  }

  return (await response.json()) as unknown;
}

async function fetchEventsFromPointer(
  pointer: string,
  signal?: AbortSignal,
): Promise<ReplayEvent[]> {
  const url = resolveUrl(pointer);
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json,text/plain",
    },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch events artifact (${response.status})`);
  }

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  const bodyText = await response.text();

  if (contentType.includes("application/json")) {
    const payload = JSON.parse(bodyText) as unknown;
    return normalizeEvents(extractRawEvents(payload));
  }

  const trimmed = bodyText.trim();
  if (!trimmed) return [];

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed) as unknown;
    return normalizeEvents(extractRawEvents(parsed));
  }

  return normalizeEvents(parseJsonLines(trimmed));
}

export async function fetchReplayList(signal?: AbortSignal): Promise<ReplayListItem[]> {
  try {
    const payload = await fetchUnknownJson(resolveReplayListUrl(), signal);
    return parseReplayList(payload);
  } catch {
    const payload = await fetchUnknownJson(resolveLocalReplayListUrl(), signal);
    return parseReplayList(payload);
  }
}

export function pickPreferredReplayId(list: ReplayListItem[]): string | null {
  const envReplayId = process.env.NEXT_PUBLIC_REPLAY_ID;
  if (envReplayId) return envReplayId;
  if (list.length === 0) return null;

  const sorted = [...list].sort((a, b) => {
    const aTs = a.createdAt ? Date.parse(a.createdAt) : Number.NaN;
    const bTs = b.createdAt ? Date.parse(b.createdAt) : Number.NaN;

    if (Number.isFinite(aTs) && Number.isFinite(bTs)) {
      return bTs - aTs;
    }

    if (Number.isFinite(aTs)) return -1;
    if (Number.isFinite(bTs)) return 1;
    return 0;
  });

  return sorted[0]?.id ?? null;
}

export async function fetchEvents(
  options: EventFetchOptions = {},
): Promise<ReplayEvent[]> {
  const { replayId, signal } = options;

  if (replayId) {
    try {
      const bundlePayload = await fetchUnknownJson(resolveReplayBundleUrl(replayId), signal);

      const inlineEvents = extractInlineEvents(bundlePayload);
      if (inlineEvents.length > 0) {
        return normalizeEvents(inlineEvents);
      }

      const pointer = extractEventPointer(bundlePayload);
      if (pointer) {
        const pointerEvents = await fetchEventsFromPointer(pointer, signal);
        if (pointerEvents.length > 0) {
          return pointerEvents;
        }
      }
    } catch {
      // Fall through to local runs bundle and then generic events endpoint.
    }

    try {
      const localBundle = await fetchUnknownJson(resolveLocalReplayBundleUrl(replayId), signal);

      const inlineEvents = extractInlineEvents(localBundle);
      if (inlineEvents.length > 0) {
        return normalizeEvents(inlineEvents);
      }

      const pointer = extractEventPointer(localBundle);
      if (pointer) {
        const pointerEvents = await fetchEventsFromPointer(pointer, signal);
        if (pointerEvents.length > 0) {
          return pointerEvents;
        }
      }
    } catch {
      // Fall back to generic events endpoint.
    }
  }

  const payload = await fetchUnknownJson(resolveRestEventsUrl(), signal);
  return normalizeEvents(extractRawEvents(payload));
}

function connectStream(url: string, handlers: StreamHandlers): StreamConnection {
  if (typeof window === "undefined" || typeof WebSocket === "undefined") {
    handlers.onError?.(new Error("WebSocket is not available"));
    return { close: () => undefined };
  }

  const stitchState = createEpisodeStitchState();
  const socket = new WebSocket(url);

  socket.onopen = () => {
    handlers.onOpen?.();
  };

  socket.onmessage = (message) => {
    if (typeof message.data !== "string") return;

    let payload: unknown;
    try {
      payload = JSON.parse(message.data);
    } catch {
      return;
    }

    const rawEvents = extractRawEvents(payload);
    const events = normalizeEvents(rawEvents, stitchState);

    events.forEach((event) => {
      handlers.onEvent(event);
    });
  };

  socket.onerror = (event) => {
    handlers.onError?.(event);
  };

  socket.onclose = (event) => {
    handlers.onClose?.(event);
  };

  return {
    close: () => {
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close();
      }
    },
  };
}

export function connectReplayStream(
  replayId: string,
  handlers: StreamHandlers,
): StreamConnection {
  return connectStream(resolveReplayStreamUrl(replayId), handlers);
}

export function connectLiveStream(
  sessionId: string,
  handlers: StreamHandlers,
): StreamConnection {
  return connectStream(resolveLiveStreamUrl(sessionId), handlers);
}

export function connectEventsStream(handlers: StreamHandlers): StreamConnection {
  const explicitWsUrl = process.env.NEXT_PUBLIC_EVENTS_WS_URL;
  const url = explicitWsUrl
    ? resolveWsUrl(explicitWsUrl)
    : resolveDefaultEventsStreamUrl();

  return connectStream(url, handlers);
}
