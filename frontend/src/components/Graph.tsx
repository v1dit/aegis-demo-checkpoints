'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Core, StylesheetJson } from 'cytoscape';
import type { ReplayEvent, ReplayTopology } from '../lib/api';

type GraphProps = {
  events?: ReplayEvent[];
  topology?: ReplayTopology | null;
  className?: string;
};

type NodeStatus = 'stable' | 'compromised' | 'contained';

type NodeKind =
  | 'gateway'
  | 'service'
  | 'workstation'
  | 'database'
  | 'identity'
  | 'cloud';

type NodeInsight = {
  id: string;
  kind: NodeKind;
  complexity: number;
  severity: number;
  attacks: number;
  defenses: number;
  lastAction: string;
  lastActor: 'RED' | 'BLUE' | 'NONE';
};

type BaseNode = {
  id: string;
  assetType?: string;
};

type BaseEdge = {
  id: string;
  source: string;
  target: string;
};

const FALLBACK_NODES: BaseNode[] = [
  { id: 'edge-gateway-01', assetType: 'gateway' },
  { id: 'identity-core', assetType: 'identity' },
  { id: 'db-vault-01', assetType: 'database' },
  { id: 'workstation-07', assetType: 'workstation' },
  { id: 'api-service-03', assetType: 'service' },
  { id: 'cloud-sync-01', assetType: 'cloud' },
  { id: 'ops-terminal-01', assetType: 'workstation' },
  { id: 'investigation-node', assetType: 'service' },
];

const FALLBACK_EDGES: BaseEdge[] = [
  { id: 'e1', source: 'edge-gateway-01', target: 'identity-core' },
  { id: 'e2', source: 'identity-core', target: 'db-vault-01' },
  { id: 'e3', source: 'identity-core', target: 'workstation-07' },
  { id: 'e4', source: 'workstation-07', target: 'api-service-03' },
  { id: 'e5', source: 'api-service-03', target: 'cloud-sync-01' },
  { id: 'e6', source: 'ops-terminal-01', target: 'investigation-node' },
  { id: 'e7', source: 'investigation-node', target: 'identity-core' },
  { id: 'e8', source: 'cloud-sync-01', target: 'db-vault-01' },
];

const STATUS_COLOR: Record<NodeStatus, string> = {
  stable: '#6b7280',
  compromised: '#ef4444',
  contained: '#38bdf8',
};

function normalizeLabel(nodeId: string): string {
  return nodeId.replaceAll('-', ' ').replaceAll('_', ' ').toUpperCase();
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function hashIntoRange(value: string, min: number, max: number): number {
  let acc = 0;
  for (let i = 0; i < value.length; i += 1) {
    acc = (acc * 31 + value.charCodeAt(i)) % 9973;
  }
  const span = max - min;
  return min + (acc % (span + 1));
}

function inferKind(id: string, assetType?: string): NodeKind {
  const raw = `${assetType ?? ''} ${id}`.toLowerCase();
  if (raw.includes('gate') || raw.includes('edge') || raw.includes('router')) return 'gateway';
  if (raw.includes('db') || raw.includes('vault') || raw.includes('sql')) return 'database';
  if (raw.includes('id') || raw.includes('auth') || raw.includes('identity')) return 'identity';
  if (raw.includes('cloud') || raw.includes('saas')) return 'cloud';
  if (raw.includes('workstation') || raw.includes('terminal') || raw.includes('laptop')) {
    return 'workstation';
  }
  return 'service';
}

function buildInsight(node: BaseNode): NodeInsight {
  const kind = inferKind(node.id, node.assetType);
  return {
    id: node.id,
    kind,
    complexity: hashIntoRange(node.id, 30, 95),
    severity: hashIntoRange(node.id, 12, 42),
    attacks: 0,
    defenses: 0,
    lastAction: 'Awaiting telemetry',
    lastActor: 'NONE',
  };
}

function suggestionForInsight(insight: NodeInsight): string {
  if (insight.attacks > insight.defenses + 2) {
    return 'Escalate isolation and rotate credentials for this asset path.';
  }
  if (insight.defenses > insight.attacks) {
    return 'Defense lead detected. Continue containment and monitor lateral links.';
  }
  return 'Balanced activity. Keep packet capture enabled for anomaly drift.';
}

function classifyAction(action: string): string {
  const normalized = action.toLowerCase();
  if (normalized.includes('exfil') || normalized.includes('dump')) return 'Data Exfiltration';
  if (normalized.includes('lateral') || normalized.includes('pivot')) return 'Lateral Movement';
  if (normalized.includes('phish') || normalized.includes('credential')) return 'Credential Abuse';
  if (normalized.includes('isolate') || normalized.includes('block') || normalized.includes('detect')) {
    return 'Defensive Response';
  }
  return 'Access/Execution';
}

export default function Graph({ events = [], topology = null, className }: GraphProps) {
  const cyContainerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const processedEventsRef = useRef(0);
  const pendingTimeoutsRef = useRef<number[]>([]);
  const insightsRef = useRef<Record<string, NodeInsight>>({});

  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeInsights, setNodeInsights] = useState<Record<string, NodeInsight>>({});

  const baseGraph = useMemo<{ nodes: BaseNode[]; edges: BaseEdge[] }>(() => {
    if (topology && topology.nodes.length > 0) {
      const nodes = topology.nodes.map((node) => ({ id: node.id, assetType: node.assetType }));
      const edges = topology.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
      }));
      return { nodes, edges };
    }

    return { nodes: FALLBACK_NODES, edges: FALLBACK_EDGES };
  }, [topology]);

  useEffect(() => {
    insightsRef.current = nodeInsights;
  }, [nodeInsights]);

  const selectedNode = selectedNodeId ? nodeInsights[selectedNodeId] ?? null : null;

  const aggregate = useMemo(() => {
    const all = Object.values(nodeInsights);
    const attacks = all.reduce((acc, node) => acc + node.attacks, 0);
    const defenses = all.reduce((acc, node) => acc + node.defenses, 0);
    const hotNodes = all
      .slice()
      .sort((a, b) => b.severity - a.severity)
      .slice(0, 4)
      .map((node) => ({ id: node.id, severity: node.severity }));

    return { attacks, defenses, hotNodes };
  }, [nodeInsights]);

  const applyReplayEvent = (event: ReplayEvent) => {
    const nextStatus: NodeStatus = event.actor === 'RED' ? 'compromised' : 'contained';

    const existing = insightsRef.current[event.target] ?? buildInsight({ id: event.target });
    const nextInsight: NodeInsight = {
      ...existing,
      attacks: existing.attacks + (event.actor === 'RED' ? 1 : 0),
      defenses: existing.defenses + (event.actor === 'BLUE' ? 1 : 0),
      lastAction: event.action,
      lastActor: event.actor,
      severity: clamp(
        existing.severity + (event.actor === 'RED' ? 8 : -6),
        8,
        100,
      ),
    };

    setNodeInsights((prev) => ({
      ...prev,
      [event.target]: nextInsight,
    }));
    insightsRef.current = {
      ...insightsRef.current,
      [event.target]: nextInsight,
    };

    const cy = cyRef.current;
    if (!cy) return;

    let node = cy.getElementById(event.target);
    if (!node.length) {
      cy.add({
        group: 'nodes',
        data: {
          id: event.target,
          label: normalizeLabel(event.target),
          size: clamp(26 + nextInsight.complexity * 0.45, 26, 74),
          kind: nextInsight.kind,
        },
      });

      node = cy.getElementById(event.target);
      cy.layout({
        name: 'cose',
        animate: true,
        animationDuration: 220,
        nodeRepulsion: 11000,
      }).run();
    }

    if (node.length) {
      const baseSize = clamp(26 + nextInsight.complexity * 0.45, 26, 74);
      node.style('background-color', STATUS_COLOR[nextStatus]);
      node.animate(
        {
          style: {
            width: baseSize + 8,
            height: baseSize + 8,
            'border-width': 2.8,
          },
        },
        {
          duration: 180,
          complete: () => {
            node.style('width', baseSize);
            node.style('height', baseSize);
            node.style('border-width', 1.8);
          },
        },
      );
    }
  };

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      if (!cyContainerRef.current || cyRef.current) return;

      const cytoscape = (await import('cytoscape')).default;
      if (!mounted) return;

      const styles: StylesheetJson = [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            color: '#f4f4f5',
            'font-size': 10,
            'font-family': 'var(--font-body)',
            'text-wrap': 'wrap',
            'text-max-width': '90px',
            'text-valign': 'center',
            'text-halign': 'center',
            width: 'data(size)',
            height: 'data(size)',
            'background-color': STATUS_COLOR.stable,
            'border-color': '#f87171',
            'border-width': 1.8,
            'text-outline-width': 0.9,
            'text-outline-color': '#08090f',
          },
        },
        {
          selector: 'node.node-selected',
          style: {
            'border-color': '#22d3ee',
            'border-width': 3,
          },
        },
        { selector: 'node[kind = "gateway"]', style: { shape: 'diamond' } },
        { selector: 'node[kind = "service"]', style: { shape: 'round-rectangle' } },
        { selector: 'node[kind = "workstation"]', style: { shape: 'hexagon' } },
        { selector: 'node[kind = "database"]', style: { shape: 'barrel' } },
        { selector: 'node[kind = "identity"]', style: { shape: 'ellipse' } },
        { selector: 'node[kind = "cloud"]', style: { shape: 'vee' } },
        {
          selector: 'edge',
          style: {
            width: 1.7,
            'line-color': '#7f1d1d',
            'target-arrow-color': '#f87171',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            opacity: 0.8,
          },
        },
      ];

      cyRef.current = cytoscape({
        container: cyContainerRef.current,
        elements: [],
        minZoom: 0.4,
        maxZoom: 2.4,
        wheelSensitivity: 0.18,
        style: styles,
      });

      const cy = cyRef.current;
      cy.on('tap', 'node', (evt) => {
        const node = evt.target;
        cy.nodes().removeClass('node-selected');
        node.addClass('node-selected');
        setSelectedNodeId(node.id());
      });

      cy.on('tap', (evt) => {
        if (evt.target === cy) {
          cy.nodes().removeClass('node-selected');
          setSelectedNodeId(null);
        }
      });
    };

    void init();

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
    const freshInsights = Object.fromEntries(
      baseGraph.nodes.map((node) => [node.id, buildInsight(node)]),
    ) as Record<string, NodeInsight>;

    setNodeInsights(freshInsights);
    insightsRef.current = freshInsights;
    setSelectedNodeId(baseGraph.nodes[0]?.id ?? null);
    processedEventsRef.current = 0;

    const cy = cyRef.current;
    if (!cy) return;

    cy.elements().remove();

    cy.add(
      baseGraph.nodes.map((node) => {
        const insight = freshInsights[node.id];
        return {
          group: 'nodes',
          data: {
            id: node.id,
            label: normalizeLabel(node.id),
            size: clamp(26 + insight.complexity * 0.45, 26, 74),
            kind: insight.kind,
          },
        };
      }),
    );

    cy.add(
      baseGraph.edges.map((edge) => ({
        group: 'edges',
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
        },
      })),
    );

    cy.layout({
      name: 'cose',
      animate: true,
      animationDuration: 540,
      nodeRepulsion: 10000,
      idealEdgeLength: 170,
      gravity: 0.45,
    }).run();
  }, [baseGraph]);

  useEffect(() => {
    if (!events.length) return;

    if (events.length < processedEventsRef.current) {
      processedEventsRef.current = 0;
      setNodeInsights((prev) => {
        const reset = Object.fromEntries(
          Object.entries(prev).map(([id, insight]) => [
            id,
            {
              ...insight,
              attacks: 0,
              defenses: 0,
              lastAction: 'Awaiting telemetry',
              lastActor: 'NONE',
            },
          ]),
        ) as Record<string, NodeInsight>;
        insightsRef.current = reset;
        return reset;
      });
    }

    const freshEvents = events.slice(processedEventsRef.current);
    freshEvents.forEach((event, idx) => {
      const timeoutId = window.setTimeout(() => {
        applyReplayEvent(event);
      }, idx * 170);
      pendingTimeoutsRef.current.push(timeoutId);
    });

    processedEventsRef.current = events.length;

    return () => {
      pendingTimeoutsRef.current.forEach((id) => window.clearTimeout(id));
      pendingTimeoutsRef.current = [];
    };
  }, [events]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const timeoutId = window.setTimeout(() => {
      cy.resize();
      cy.fit(undefined, isExpanded ? 92 : 48);
    }, 160);

    return () => window.clearTimeout(timeoutId);
  }, [isExpanded]);

  const shellClass = isExpanded
    ? 'fixed inset-0 z-[70] bg-[#020307]/95 p-4 md:p-6'
    : className ?? 'h-[560px]';

  const openRatio =
    aggregate.attacks + aggregate.defenses === 0
      ? 0
      : Math.round((aggregate.attacks / (aggregate.attacks + aggregate.defenses)) * 100);

  return (
    <div className={shellClass}>
      <section className="aegis-card relative h-full overflow-hidden p-4">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display text-sm uppercase tracking-[0.24em] text-[#fecaca]">
              Threat Topology Matrix
            </h3>
            <p className="text-xs text-[#fca5a5]">
              Drag nodes to reposition, zoom to inspect, click a node for attack/defense context.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="rounded-md border border-red-500/50 bg-red-950/30 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-red-100">
              Open pressure {openRatio}%
            </div>
            <button
              type="button"
              onClick={() => setIsExpanded((prev) => !prev)}
              className="rounded-md border border-cyan-400/60 bg-cyan-500/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-cyan-100 transition hover:bg-cyan-400/20"
            >
              {isExpanded ? 'Collapse View' : 'Expand View'}
            </button>
          </div>
        </header>

        <div className="grid h-[calc(100%-4.4rem)] gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div
            ref={cyContainerRef}
            className="h-full min-h-[320px] rounded-xl border border-red-500/30 bg-[#06070d]"
            aria-label="interactive threat topology graph"
          />

          <aside className="rounded-xl border border-red-500/30 bg-[#080a11]/90 p-3">
            <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
              <Metric label="Attacks" value={aggregate.attacks} tone="text-[#f87171]" />
              <Metric label="Defenses" value={aggregate.defenses} tone="text-[#38bdf8]" />
            </div>

            <div className="mb-3 rounded-lg border border-red-500/25 bg-black/30 p-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[#fca5a5]">Node Intelligence</div>
              {selectedNode ? (
                <div className="mt-2 space-y-2 text-xs text-[#e5e7eb]">
                  <div className="font-display text-sm tracking-wide text-[#fee2e2]">
                    {normalizeLabel(selectedNode.id)}
                  </div>
                  <InfoRow label="Class" value={selectedNode.kind} />
                  <InfoRow label="Threat score" value={`${selectedNode.severity}/100`} />
                  <InfoRow label="Complexity" value={`${selectedNode.complexity}/100`} />
                  <InfoRow label="Attack actions" value={selectedNode.attacks} />
                  <InfoRow label="Defense actions" value={selectedNode.defenses} />
                  <InfoRow label="Latest signal" value={classifyAction(selectedNode.lastAction)} />
                  <div className="rounded-md border border-cyan-500/30 bg-cyan-950/20 p-2 text-[11px] leading-relaxed text-cyan-100">
                    {suggestionForInsight(selectedNode)}
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-[#a1a1aa]">Select any node to inspect mission context.</p>
              )}
            </div>

            <div className="rounded-lg border border-red-500/25 bg-black/30 p-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[#fca5a5]">Hot Assets</div>
              <ul className="mt-2 space-y-1 text-xs text-[#e4e4e7]">
                {aggregate.hotNodes.map((node) => (
                  <li key={node.id} className="flex items-center justify-between">
                    <span>{normalizeLabel(node.id)}</span>
                    <span className="font-semibold text-red-300">{node.severity}</span>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="rounded-md border border-red-500/20 bg-black/25 px-2 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-[#a1a1aa]">{label}</div>
      <div className={`font-display text-lg ${tone}`}>{value}</div>
    </div>
  );
}

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-white/10 pb-1 text-[11px]">
      <span className="uppercase tracking-[0.12em] text-[#a1a1aa]">{label}</span>
      <span className="text-right text-[#f4f4f5]">{value}</span>
    </div>
  );
}
