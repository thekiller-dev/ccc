import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { GraphDocument, NodeType, RelationType } from './types'

interface GraphCanvasProps {
  graph: GraphDocument
  activeNodeTypes: ReadonlySet<NodeType>
  activeRelationTypes: ReadonlySet<RelationType>
  query: string
  selectedNodeId: string | null
  visibleNodeCount: number
  onSelectNode: (nodeId: string | null) => void
}

type GraphStyles = NonNullable<cytoscape.CytoscapeOptions['style']>

const graphStyle: GraphStyles = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      color: '#d7dfef',
      'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif',
      'font-size': 10,
      'font-weight': 500,
      'text-wrap': 'ellipsis',
      'text-max-width': '128px',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 8,
      'text-outline-color': '#0b1020',
      'text-outline-width': 2,
      'background-color': '#7c83fd',
      'border-width': 1,
      'border-color': '#c4c9ff',
      'overlay-color': '#a5b4fc',
      'overlay-opacity': 0,
      width: 34,
      height: 34,
      'min-zoomed-font-size': 8,
    },
  },
  {
    selector: 'node[type = "project"]',
    style: {
      'background-color': '#8b5cf6',
      'border-color': '#c4b5fd',
      width: 48,
      height: 48,
      'font-size': 12,
      'font-weight': 700,
    },
  },
  {
    selector: 'node[type = "file"]',
    style: {
      shape: 'round-rectangle',
      'background-color': '#2563eb',
      'border-color': '#60a5fa',
      width: 38,
      height: 29,
    },
  },
  {
    selector: 'node[type = "module"]',
    style: {
      shape: 'round-rectangle',
      'background-color': '#334155',
      'border-color': '#94a3b8',
      width: 36,
      height: 27,
    },
  },
  {
    selector: 'node[type = "function"]',
    style: {
      shape: 'ellipse',
      'background-color': '#0e7490',
      'border-color': '#67e8f9',
    },
  },
  {
    selector: 'node[type = "class"]',
    style: {
      shape: 'round-rectangle',
      'background-color': '#a16207',
      'border-color': '#facc15',
      width: 40,
      height: 31,
    },
  },
  {
    selector: 'node[type = "interface"]',
    style: {
      shape: 'diamond',
      'background-color': '#047857',
      'border-color': '#6ee7b7',
    },
  },
  {
    selector: 'node[type = "type"]',
    style: {
      shape: 'hexagon',
      'background-color': '#9d174d',
      'border-color': '#f9a8d4',
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.35,
      'line-color': '#526078',
      'target-arrow-color': '#74829b',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.72,
      'curve-style': 'bezier',
      opacity: 0.66,
    },
  },
  {
    selector: 'edge[type = "CONTAINS"]',
    style: { 'line-color': '#536174', 'target-arrow-color': '#65758d' },
  },
  {
    selector: 'edge[type = "DEFINES"]',
    style: { 'line-color': '#818cf8', 'target-arrow-color': '#a5b4fc' },
  },
  {
    selector: 'edge[type = "IMPORTS"]',
    style: { 'line-color': '#38bdf8', 'target-arrow-color': '#7dd3fc' },
  },
  {
    selector: 'edge[type = "CALLS"]',
    style: { 'line-color': '#34d399', 'target-arrow-color': '#6ee7b7', width: 1.8 },
  },
  {
    selector: 'edge[type = "EXTENDS"]',
    style: { 'line-color': '#fbbf24', 'target-arrow-color': '#fde68a', width: 1.8 },
  },
  {
    selector: 'edge[type = "IMPLEMENTS"]',
    style: { 'line-color': '#f472b6', 'target-arrow-color': '#f9a8d4', width: 1.8 },
  },
  {
    selector: 'edge[inferred = true]',
    style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 4] },
  },
  {
    selector: 'node.is-active',
    style: {
      'border-width': 3,
      'border-color': '#f8fafc',
      'overlay-opacity': 0.16,
      'overlay-color': '#c4b5fd',
    },
  },
  {
    selector: 'node.search-match',
    style: { 'border-width': 3, 'border-color': '#fbbf24', 'z-index': 999 },
  },
  {
    selector: 'node.search-muted, edge.search-muted',
    style: { opacity: 0.09 },
  },
  {
    selector: 'node.filtered-out, edge.filtered-out',
    style: { display: 'none' },
  },
]

export function GraphCanvas({
  graph,
  activeNodeTypes,
  activeRelationTypes,
  query,
  selectedNodeId,
  visibleNodeCount,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const selectionHandlerRef = useRef(onSelectNode)

  useEffect(() => {
    selectionHandlerRef.current = onSelectNode
  }, [onSelectNode])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const elements: cytoscape.ElementDefinition[] = [
      ...graph.nodes.map((node) => ({
        data: { ...node, label: node.name },
      })),
      ...graph.relations.map((relation) => ({
        data: {
          ...relation,
          source: relation.source,
          target: relation.target,
        },
      })),
    ]

    const cy = cytoscape({
      container,
      elements,
      style: graphStyle,
      minZoom: 0.18,
      maxZoom: 2.5,
      wheelSensitivity: 0.2,
      boxSelectionEnabled: false,
      layout: {
        name: 'cose',
        animate: false,
        fit: true,
        padding: 48,
        nodeRepulsion: 4200,
        idealEdgeLength: 92,
        edgeElasticity: 90,
        gravity: 0.22,
        numIter: 650,
      },
    })

    cyRef.current = cy
    cy.on('tap', 'node', (event) => {
      selectionHandlerRef.current(event.target.id())
    })
    cy.on('tap', (event) => {
      if (event.target === cy) selectionHandlerRef.current(null)
    })
    cy.ready(() => cy.fit(undefined, 42))

    const resizeObserver = new ResizeObserver(() => cy.resize())
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      cy.destroy()
      if (cyRef.current === cy) cyRef.current = null
    }
  }, [graph])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('is-active')
    if (selectedNodeId) cy.getElementById(selectedNodeId).addClass('is-active')
  }, [graph, selectedNodeId])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    const normalizedQuery = query.trim().toLocaleLowerCase()
    const matchingNodeIds = new Set<string>()
    const visibleNodeIds = new Set<string>()

    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const nodeType = node.data('type') as NodeType
        const isVisible = activeNodeTypes.has(nodeType)
        const searchableText = [node.data('name'), node.data('path'), node.id()]
          .filter(Boolean)
          .join(' ')
          .toLocaleLowerCase()
        const isMatch = !normalizedQuery || searchableText.includes(normalizedQuery)

        node.toggleClass('filtered-out', !isVisible)
        node.toggleClass('search-match', Boolean(normalizedQuery) && isMatch)
        node.toggleClass('search-muted', Boolean(normalizedQuery) && !isMatch)
        if (isVisible) visibleNodeIds.add(node.id())
        if (isVisible && isMatch) matchingNodeIds.add(node.id())
      })

      cy.edges().forEach((edge) => {
        const relationType = edge.data('type') as RelationType
        const isVisible =
          activeRelationTypes.has(relationType) &&
          visibleNodeIds.has(edge.data('source')) &&
          visibleNodeIds.has(edge.data('target'))
        const isSearchMatch =
          !normalizedQuery ||
          matchingNodeIds.has(edge.data('source')) ||
          matchingNodeIds.has(edge.data('target'))

        edge.toggleClass('filtered-out', !isVisible)
        edge.toggleClass('search-muted', Boolean(normalizedQuery) && !isSearchMatch)
      })
    })
  }, [graph, activeNodeTypes, activeRelationTypes, query])

  const zoom = (factor: number) => {
    const cy = cyRef.current
    if (cy) cy.zoom(Math.min(2.5, Math.max(0.18, cy.zoom() * factor)))
  }

  const fit = () => {
    const cy = cyRef.current
    if (cy) cy.fit(undefined, 42)
  }

  return (
    <div className="graph-stage">
      <div className="graph-grid" aria-hidden="true" />
      <div ref={containerRef} className="cytoscape-root" aria-label="Graphe interactif du projet" />
      {visibleNodeCount === 0 && (
        <div className="graph-overlay-empty">
          <span className="empty-orbit">
            <span />
          </span>
          <strong>Aucun élément visible</strong>
          <span>Ajustez la recherche ou les filtres pour retrouver des éléments.</span>
        </div>
      )}
      <div className="graph-controls" aria-label="Contrôles du graphe">
        <button type="button" onClick={() => zoom(1.18)} aria-label="Zoom avant" title="Zoom avant">
          <span>+</span>
        </button>
        <button type="button" onClick={() => zoom(1 / 1.18)} aria-label="Zoom arrière" title="Zoom arrière">
          <span>−</span>
        </button>
        <div className="control-divider" />
        <button type="button" onClick={fit} aria-label="Centrer le graphe" title="Centrer le graphe">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M7 3H3v4M13 3h4v4M17 13v4h-4M7 17H3v-4" />
            <path d="M7 7 3 3m10 4 4-4m-4 10 4 4M7 13l-4 4" />
          </svg>
        </button>
      </div>
      <div className="canvas-hint">
        <span className="hint-dot" />
        Glisser pour déplacer <span className="hint-separator">·</span> Molette pour zoomer
      </div>
    </div>
  )
}
