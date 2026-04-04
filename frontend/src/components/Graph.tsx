'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Core } from 'cytoscape';

type Actor = 'RED' | 'BLUE';

export type ReplayEvent = {
  step?: number;
  actor: Actor;
  action: string;
  target: string;
};

type GraphProps = {
  /**
   * Event stream from replay/log system.
   * Graph consumes the same data used to render logs.
   */
  events?: ReplayEvent[];
  className?: string;
};

type NodeStatus = 'neutral' | 'compromised' | 'defended';

const STATUS_COLORS: Record<NodeStatus, string> = {
  neutral: '#9CA3AF',
  compromised: '#EF4444',
  defended: '#3B82F6',
};

const MOCK_NODES = [
  'host-01',
  'host-02',
  'host-03',
  'host-04',
  'host-05',
  'host-06',
  'host-07',
  'host-08',
  'host-09',
  'host-10',
];

const MOCK_EDGES: Array<[string, string]> = [
  ['host-01', 'host-02'],
  ['host-01', 'host-03'],
  ['host-02', 'host-04'],
  ['host-02', 'host-05'],
  ['host-03', 'host-06'],
  ['host-03', 'host-07'],
  ['host-05', 'host-08'],
  ['host-06', 'host-08'],
  ['host-07', 'host-09'],
  ['host-08', 'host-10'],
  ['host-09', 'host-10'],
];

export default function Graph({ events = [], className }: GraphProps) {
  const cyContainerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const processedEventsRef = useRef(0);
  const pendingTimeoutsRef = useRef<number[]>([]);

  const [statusByNode, setStatusByNode] = useState<Record<string, NodeStatus>>(() =>
    Object.fromEntries(MOCK_NODES.map((id) => [id, 'neutral'])) as Record<string, NodeStatus>,
  );
  const [logLines, setLogLines] = useState<string[]>(['[boot] replay graph online']);

  const metricCounts = useMemo(() => {
    const compromised = Object.values(statusByNode).filter((s) => s === 'compromised').length;
    const defended = Object.values(statusByNode).filter((s) => s === 'defended').length;
    const neutral = Object.values(statusByNode).filter((s) => s === 'neutral').length;
    return { compromised, defended, neutral };
  }, [statusByNode]);

  const applyReplayEvent = (evt: ReplayEvent) => {
    const nextStatus: NodeStatus = evt.actor === 'RED' ? 'compromised' : 'defended';

    setStatusByNode((prev) => ({ ...prev, [evt.target]: nextStatus }));
    setLogLines((prev) => {
      const prefix = typeof evt.step === 'number' ? `[step ${evt.step}]` : '[step ?]';
      const line = `${prefix} ${evt.actor} ${evt.action} ${evt.target}`;
      return [...prev.slice(-11), line];
    });

    const cy = cyRef.current;
    if (!cy) return;

    const node = cy.getElementById(evt.target);
    if (node?.length) {
      node.animate(
        {
          style: {
            'background-color': STATUS_COLORS[nextStatus],
          },
        },
        {
          duration: 450,
        },
      );

      if (evt.action === 'isolate' || evt.action === 'disconnect' || evt.action === 'remove_edge') {
        const connectedEdges = node.connectedEdges();
        connectedEdges.animate(
          {
            style: { opacity: 0 },
          },
          {
            duration: 350,
            complete: () => connectedEdges.remove(),
          },
        );
      }
    }
  };

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      if (!cyContainerRef.current || cyRef.current) return;

      const cytoscape = (await import('cytoscape')).default;
      if (!mounted) return;

      const elements = [
        ...MOCK_NODES.map((id) => ({ data: { id, label: id.toUpperCase() } })),
        ...MOCK_EDGES.map(([source, target]) => ({
          data: { id: `${source}=>${target}`, source, target },
        })),
      ];

      cyRef.current = cytoscape({
        container: cyContainerRef.current,
        elements,
        layout: {
          name: 'cose',
          animate: true,
          animationDuration: 700,
          nodeRepulsion: 6000,
          idealEdgeLength: 120,
        },
        style: [
          {
            selector: 'node',
            style: {
              label: 'data(label)',
              color: '#E5E7EB',
              'font-size': 10,
              'text-valign': 'center',
              'text-halign': 'center',
              'background-color': STATUS_COLORS.neutral,
              width: 34,
              height: 34,
              'border-width': 2,
              'border-color': '#111827',
            },
          },
          {
            selector: 'edge',
            style: {
              width: 2,
              'line-color': '#4B5563',
              'curve-style': 'bezier',
              opacity: 0.9,
            },
          },
        ],
      });
    };

    init();

    return () => {
      mounted = false;
      pendingTimeoutsRef.current.forEach((id) => window.clearTimeout(id));
      pendingTimeoutsRef.current = [];
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!events?.length) return;

    // If caller resets the event list, reset graph replay cursor.
    if (events.length < processedEventsRef.current) {
      processedEventsRef.current = 0;
      setStatusByNode(Object.fromEntries(MOCK_NODES.map((id) => [id, 'neutral'])) as Record<string, NodeStatus>);
    }

    const freshEvents = events.slice(processedEventsRef.current);
    freshEvents.forEach((event, idx) => {
      const timeoutId = window.setTimeout(() => {
        applyReplayEvent(event);
      }, idx * 200);
      pendingTimeoutsRef.current.push(timeoutId);
    });

    processedEventsRef.current = events.length;

    return () => {
      pendingTimeoutsRef.current.forEach((id) => window.clearTimeout(id));
      pendingTimeoutsRef.current = [];
    };
  }, [events]);

  return (
    <section className={`h-full w-full bg-[#0b0f17] p-4 text-gray-100 ${className ?? ''}`}>
      <header className="mb-4 rounded-xl border border-blue-500 bg-[#111827] p-4 shadow-[0_0_25px_rgba(59,130,246,0.3)]">
        <h1 className="text-xl font-semibold tracking-wide">Cyber RL Dashboard</h1>
      </header>

      <div className="grid h-[calc(100%-4.5rem)] grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-gray-800 bg-[#111827] p-3 lg:col-span-2">
          <div className="mb-2 flex items-center justify-between text-sm text-gray-300">
            <span>Attack Surface Graph</span>
            <span className="text-yellow-400">live replay</span>
          </div>
          <div
            ref={cyContainerRef}
            className="h-[430px] w-full rounded-lg border border-gray-800 bg-black/40"
            aria-label="network graph"
          />
        </div>

        <aside className="rounded-xl border border-gray-800 bg-[#111827] p-4">
          <h2 className="mb-4 text-sm uppercase tracking-wider text-gray-400">System Metrics</h2>
          <div className="space-y-3">
            <MetricCard label="Threat Level" value="High" colorClass="text-red-500" />
            <MetricCard label="Compromised" value={metricCounts.compromised} colorClass="text-red-500" />
            <MetricCard label="Defended" value={metricCounts.defended} colorClass="text-blue-500" />
            <MetricCard label="Neutral" value={metricCounts.neutral} colorClass="text-gray-400" />
          </div>
        </aside>

        <div className="rounded-xl border border-green-500 bg-black p-4 lg:col-span-3">
          <h2 className="mb-3 text-sm uppercase tracking-wider text-gray-400">Logs</h2>
          <div className="max-h-[220px] overflow-auto rounded-lg border border-gray-800 bg-black/50 p-3 font-mono text-sm text-green-400">
            {logLines.map((line, idx) => (
              <div key={`${line}-${idx}`} className="whitespace-pre-wrap">
                {line}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: number | string;
  colorClass: string;
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-black/40 p-3">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`text-2xl font-semibold ${colorClass}`}>{value}</div>
    </div>
  );
}
