import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type {
  GraphDocument,
  GraphNode,
  GraphRelation,
  HealthResponse,
  NodeType,
  ProjectStats,
  RelationType,
  ScanResponse,
} from './types'
import './App.css'

type IconName =
  | 'activity'
  | 'alert'
  | 'arrow-left'
  | 'arrow-right'
  | 'branch'
  | 'check'
  | 'chevron'
  | 'close'
  | 'copy'
  | 'file'
  | 'filter'
  | 'folder'
  | 'function'
  | 'graph'
  | 'layers'
  | 'link'
  | 'lock'
  | 'search'
  | 'scan'
  | 'shield'
  | 'spark'
  | 'type'
  | 'zoom'

const NODE_PRESENTATION: Record<NodeType, { label: string; color: string; icon: IconName }> = {
  project: { label: 'Projet', color: '#a78bfa', icon: 'graph' },
  file: { label: 'Fichiers', color: '#60a5fa', icon: 'file' },
  function: { label: 'Fonctions', color: '#67e8f9', icon: 'function' },
  class: { label: 'Classes', color: '#facc15', icon: 'layers' },
  interface: { label: 'Interfaces', color: '#6ee7b7', icon: 'type' },
  type: { label: 'Types', color: '#f9a8d4', icon: 'type' },
  module: { label: 'Modules', color: '#94a3b8', icon: 'folder' },
}

const RELATION_PRESENTATION: Record<RelationType, { label: string; color: string }> = {
  CONTAINS: { label: 'Contient', color: '#74829b' },
  DEFINES: { label: 'Définit', color: '#a5b4fc' },
  IMPORTS: { label: 'Importe', color: '#7dd3fc' },
  CALLS: { label: 'Appelle', color: '#6ee7b7' },
  EXTENDS: { label: 'Hérite de', color: '#fde68a' },
  IMPLEMENTS: { label: 'Implémente', color: '#f9a8d4' },
}

const NODE_TYPES = Object.keys(NODE_PRESENTATION) as NodeType[]
const RELATION_TYPES = Object.keys(RELATION_PRESENTATION) as RelationType[]
const GraphCanvas = lazy(() =>
  import('./GraphCanvas').then((module) => ({ default: module.GraphCanvas })),
)

function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    activity: <><path d="M3 12h3l2-7 4 14 2-7h7" /></>,
    alert: <><path d="M10.3 3.9 2.8 17a1.2 1.2 0 0 0 1 1.8h15a1.2 1.2 0 0 0 1-1.8L12.3 3.9a1.2 1.2 0 0 0-2 0Z" /><path d="M11.3 8v4.5m0 3h.01" /></>,
    'arrow-left': <><path d="m12 5-7 7 7 7" /><path d="M19 12H5" /></>,
    'arrow-right': <><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></>,
    branch: <><circle cx="6" cy="5" r="2" /><circle cx="18" cy="7" r="2" /><circle cx="18" cy="17" r="2" /><path d="M8 5h3a4 4 0 0 1 4 4v4a4 4 0 0 0 4 4" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    chevron: <><path d="m7 10 5 5 5-5" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></>,
    file: <><path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Z" /><path d="M13 3v7h7M8 14h8m-8 4h8" /></>,
    filter: <><path d="M4 5h16l-6.3 7.2v5.1L10.3 19v-6.8Z" /></>,
    folder: <><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></>,
    function: <><path d="M15 4h-2a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3H5m0-9h10" /><path d="M15 11h4m-2-2v4" /></>,
    graph: <><circle cx="5" cy="6" r="2.2" /><circle cx="18.5" cy="5" r="2.2" /><circle cx="12" cy="18" r="2.2" /><path d="m7 7.3 3.6 8.1m6.3-8.6-3.8 8.6M7.2 6h9" /></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5m-18 5 9 5 9-5" /></>,
    link: <><path d="M10 13a5 5 0 0 0 7.1 0l3-3A5 5 0 0 0 13 2.9l-1.7 1.7" /><path d="M14 11a5 5 0 0 0-7.1 0l-3 3A5 5 0 0 0 11 21.1l1.7-1.7" /></>,
    lock: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    scan: <><path d="M7 3H5a2 2 0 0 0-2 2v2m14-4h2a2 2 0 0 1 2 2v2M3 17v2a2 2 0 0 0 2 2h2m14-4v2a2 2 0 0 1-2 2h-2" /><path d="M7 12h10" /></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z" /><path d="m9 12 2 2 4-4" /></>,
    spark: <><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3Z" /><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></>,
    type: <><path d="M4 6V4h16v2M12 4v16m-4 0h8" /></>,
    zoom: <><path d="M8 3H5a2 2 0 0 0-2 2v3m11-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m11-5v3a2 2 0 0 1-2 2h-3" /><path d="M8 12h8" /></>,
  }

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name]}
    </svg>
  )
}

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <path d="M10 11.5 25.5 9m-15 17.5 15-7M11 13l-1 12m3-12 11-2m-9 7 8 3" stroke="url(#brand-line)" strokeWidth="1.6" />
      <circle cx="9" cy="11" r="3.3" fill="#10182a" stroke="#8b9cff" strokeWidth="1.5" />
      <circle cx="26.5" cy="8.5" r="3.3" fill="#10182a" stroke="#38d5c3" strokeWidth="1.5" />
      <circle cx="10" cy="26" r="3.3" fill="#10182a" stroke="#a78bfa" strokeWidth="1.5" />
      <circle cx="26" cy="20" r="3.3" fill="#10182a" stroke="#60a5fa" strokeWidth="1.5" />
      <defs><linearGradient id="brand-line" x1="9" y1="8" x2="27" y2="27" gradientUnits="userSpaceOnUse"><stop stopColor="#8B9CFF" /><stop offset="1" stopColor="#38D5C3" /></linearGradient></defs>
    </svg>
  )
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : null
    const message = typeof detail === 'string' ? detail : `La requête a échoué (HTTP ${response.status}).`
    throw new Error(message)
  }
  return payload as T
}

function formatCount(value: number) {
  return value.toLocaleString('fr-FR')
}

function formatNodeType(type: NodeType) {
  return NODE_PRESENTATION[type]?.label.replace(/s$/, '') ?? type
}

function relationLabel(type: RelationType) {
  return RELATION_PRESENTATION[type]?.label ?? type
}

function App() {
  const [projectPath, setProjectPath] = useState('')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [graph, setGraph] = useState<GraphDocument | null>(null)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [remoteSelectedNode, setRemoteSelectedNode] = useState<GraphNode | null>(null)
  const [activeNodeTypes, setActiveNodeTypes] = useState<ReadonlySet<NodeType>>(
    () => new Set(NODE_TYPES),
  )
  const [activeRelationTypes, setActiveRelationTypes] = useState<ReadonlySet<RelationType>>(
    () => new Set(RELATION_TYPES),
  )
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true
    requestJson<HealthResponse>('/health')
      .then(() => {
        if (active) setApiStatus('online')
      })
      .catch(() => {
        if (active) setApiStatus('offline')
      })
    return () => {
      active = false
    }
  }, [])

  const scanProject = useCallback(async (pathOverride?: string) => {
    const requestedPath = (pathOverride ?? projectPath).trim()
    if (!requestedPath) {
      setError('Saisissez le chemin d’un dossier de projet à analyser.')
      return
    }

    setError(null)
    setLoading(true)
    try {
      const scan = await requestJson<ScanResponse>('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: requestedPath }),
      })
      const [nextGraph, nextStats] = await Promise.all([
        requestJson<GraphDocument>(`/api/projects/${scan.project_id}/graph`),
        requestJson<ProjectStats>(`/api/projects/${scan.project_id}/stats`),
      ])
      setProjectPath(requestedPath)
      setProjectId(scan.project_id)
      setGraph(nextGraph)
      setStats(nextStats ?? scan.stats)
      setRemoteSelectedNode(null)
      setSelectedNodeId(
        nextGraph.nodes.find((node) => node.type === 'file')?.id ??
          nextGraph.nodes[0]?.id ??
          null,
      )
      setQuery('')
      setActiveNodeTypes(new Set(NODE_TYPES))
      setActiveRelationTypes(new Set(RELATION_TYPES))
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Une erreur inattendue est survenue.')
      setApiStatus((current) => (current === 'checking' ? 'offline' : current))
    } finally {
      setLoading(false)
    }
  }, [projectPath])

  useEffect(() => {
    if (!projectId || !selectedNodeId) return

    let active = true
    const encodedNodeId = encodeURIComponent(selectedNodeId)
    requestJson<GraphNode>(`/api/projects/${projectId}/nodes/${encodedNodeId}`)
      .then((node) => {
        if (active) setRemoteSelectedNode(node)
      })
      .catch(() => {
        // The graph response already contains the node if the detail request fails.
      })
    return () => {
      active = false
    }
  }, [projectId, selectedNodeId])

  const nodeCounts = useMemo(() => {
    const counts = Object.fromEntries(NODE_TYPES.map((type) => [type, 0])) as Record<NodeType, number>
    for (const node of graph?.nodes ?? []) counts[node.type] = (counts[node.type] ?? 0) + 1
    return counts
  }, [graph])

  const relationCounts = useMemo(() => {
    const counts = Object.fromEntries(RELATION_TYPES.map((type) => [type, 0])) as Record<
      RelationType,
      number
    >
    for (const relation of graph?.relations ?? []) {
      counts[relation.type] = (counts[relation.type] ?? 0) + 1
    }
    return counts
  }, [graph])

  const visibleNodeCount = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase()
    return (graph?.nodes ?? []).filter((node) => {
      if (!activeNodeTypes.has(node.type)) return false
      if (!normalizedQuery) return true
      return [node.name, node.path, node.id]
        .join(' ')
        .toLocaleLowerCase()
        .includes(normalizedQuery)
    }).length
  }, [activeNodeTypes, graph, query])

  const nodeById = useMemo(
    () => new Map((graph?.nodes ?? []).map((node) => [node.id, node])),
    [graph],
  )
  const selectedNode =
    (remoteSelectedNode?.id === selectedNodeId ? remoteSelectedNode : null) ??
    graph?.nodes.find((node) => node.id === selectedNodeId) ??
    null

  const selectedRelations = useMemo(
    () => graph?.relations.filter((relation) => relation.source === selectedNodeId || relation.target === selectedNodeId) ?? [],
    [graph, selectedNodeId],
  )

  const toggleNodeType = (type: NodeType) => {
    setActiveNodeTypes((current) => {
      const next = new Set(current)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const toggleRelationType = (type: RelationType) => {
    setActiveRelationTypes((current) => {
      const next = new Set(current)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void scanProject()
  }

  const handleCopyId = async () => {
    if (!selectedNode) return
    try {
      await navigator.clipboard.writeText(selectedNode.id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  const projectName = stats?.project ?? graph?.nodes.find((node) => node.type === 'project')?.name ?? ''
  const projectLocation = graph?.metadata.project_path || projectPath || '.'

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#top" aria-label="CodeGraph, accueil">
          <BrandMark />
          <span className="brand-name">Code<span>Graph</span></span>
          <span className="brand-edition">LOCAL</span>
        </a>

        <form className="project-form" onSubmit={handleSubmit}>
          <label className="project-form-label" htmlFor="project-path">DOSSIER À ANALYSER</label>
          <div className="path-input-wrap">
            <Icon name="folder" size={17} />
            <input
              id="project-path"
              type="text"
              value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)}
              placeholder="Chemin relatif ou absolu autorisé"
              autoComplete="off"
              spellCheck={false}
              aria-label="Chemin du projet"
            />
            <button className="sample-link" type="button" onClick={() => void scanProject('examples/demo-ts')}>
              <Icon name="spark" size={14} />
              <span>Démo</span>
            </button>
            <button className="analyze-button" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : <Icon name="scan" size={16} />}
              <span>{loading ? 'Analyse…' : 'Analyser'}</span>
            </button>
          </div>
        </form>

        <div className={`api-status api-status-${apiStatus}`} title="État de l’API locale">
          <span className="status-pulse" />
          <span className="api-status-copy">
            <strong>{apiStatus === 'online' ? 'API connectée' : apiStatus === 'checking' ? 'Connexion…' : 'API hors ligne'}</strong>
            <span>{apiStatus === 'online' ? 'Traitement local' : '127.0.0.1:8000'}</span>
          </span>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <Icon name="alert" size={17} />
          <span>{error}</span>
          <button type="button" aria-label="Fermer le message" onClick={() => setError(null)}>
            <Icon name="close" size={15} />
          </button>
        </div>
      )}

      <main className={`main-content ${graph && stats ? 'has-project' : 'is-welcome'}`} id="top">
        {graph && stats ? (
          <>
            <section className="project-overview" aria-label="Résumé du projet analysé">
              <div className="project-heading">
                <div className="project-icon"><Icon name="folder" size={19} /></div>
                <div className="project-title-block">
                  <span className="eyebrow">PROJET ANALYSÉ</span>
                  <h1>{projectName}</h1>
                  <span className="project-path" title={projectLocation}>
                    <Icon name="folder" size={12} />
                    {projectLocation}
                  </span>
                </div>
                <div className="schema-pill">SCHÉMA {graph.schema_version}</div>
              </div>
              <div className="overview-stats">
                <StatCard icon="file" label="Fichiers" value={stats.files} accent="blue" />
                <StatCard icon="layers" label="Symboles" value={stats.symbols} accent="violet" />
                <StatCard icon="branch" label="Relations" value={stats.relations} accent="mint" />
                <StatCard
                  icon={stats.issues > 0 ? 'alert' : 'check'}
                  label="Diagnostics"
                  value={stats.issues}
                  accent={stats.issues > 0 ? 'amber' : 'mint'}
                />
              </div>
            </section>

            <section className="workspace" aria-label="Exploration du graphe">
              <aside className="explorer-panel">
                <div className="panel-heading">
                  <div>
                    <span className="panel-kicker">EXPLORATEUR</span>
                    <strong>Vue du projet</strong>
                  </div>
                  <span className="panel-count">{formatCount(graph.nodes.length)}</span>
                </div>

                <div className="side-section">
                  <div className="side-section-heading">
                    <span><Icon name="layers" size={14} /> Types de nœuds</span>
                    <button
                      className="reset-filter"
                      type="button"
                      onClick={() => setActiveNodeTypes(new Set(NODE_TYPES))}
                      title="Afficher tous les types"
                    >
                      Tout
                    </button>
                  </div>
                  <div className="filter-list">
                    {NODE_TYPES.map((type) => {
                      const presentation = NODE_PRESENTATION[type]
                      const enabled = activeNodeTypes.has(type)
                      return (
                        <button
                          className={`filter-row ${enabled ? '' : 'is-disabled'}`}
                          type="button"
                          key={type}
                          aria-pressed={enabled}
                          onClick={() => toggleNodeType(type)}
                        >
                          <span className="filter-icon" style={{ color: presentation.color }}>
                            <Icon name={presentation.icon} size={14} />
                          </span>
                          <span className="filter-label">{presentation.label}</span>
                          <span className="filter-count">{formatCount(nodeCounts[type])}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div className="side-section relation-section">
                  <div className="side-section-heading">
                    <span><Icon name="link" size={14} /> Relations</span>
                    <button
                      className="reset-filter"
                      type="button"
                      onClick={() => setActiveRelationTypes(new Set(RELATION_TYPES))}
                      title="Afficher tous les types de relation"
                    >
                      Tout
                    </button>
                  </div>
                  <div className="filter-list relation-list">
                    {RELATION_TYPES.map((type) => {
                      const presentation = RELATION_PRESENTATION[type]
                      const enabled = activeRelationTypes.has(type)
                      return (
                        <button
                          className={`filter-row ${enabled ? '' : 'is-disabled'}`}
                          type="button"
                          key={type}
                          aria-pressed={enabled}
                          onClick={() => toggleRelationType(type)}
                        >
                          <span className="relation-swatch" style={{ backgroundColor: presentation.color }} />
                          <span className="filter-label">{presentation.label}</span>
                          <span className="filter-count">{formatCount(relationCounts[type])}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div className="side-section files-section">
                  <div className="side-section-heading">
                    <span><Icon name="folder" size={14} /> Fichiers sources</span>
                    <span className="muted-count">{formatCount(nodeCounts.file)}</span>
                  </div>
                  <div className="file-list">
                    {graph.nodes.filter((node) => node.type === 'file').length > 0 ? (
                      graph.nodes
                        .filter((node) => node.type === 'file')
                        .sort((left, right) => left.path.localeCompare(right.path))
                        .map((node) => (
                          <button
                            className={`file-row ${selectedNodeId === node.id ? 'is-selected' : ''}`}
                            key={node.id}
                            type="button"
                            onClick={() => setSelectedNodeId(node.id)}
                            title={node.path}
                          >
                            <Icon name="file" size={14} />
                            <span>{node.path}</span>
                          </button>
                        ))
                    ) : (
                      <p className="side-empty">Aucun fichier source.</p>
                    )}
                  </div>
                </div>

                <div className="local-footnote">
                  <span className="local-lock"><Icon name="lock" size={13} /></span>
                  <span>Le code reste sur cette machine.</span>
                </div>
              </aside>

              <section className="graph-panel" aria-label="Graphe de dépendances">
                <div className="graph-toolbar">
                  <div className="graph-heading">
                    <div className="graph-heading-icon"><Icon name="graph" size={17} /></div>
                    <div>
                      <h2>Graphe de connaissances</h2>
                      <span>{formatCount(visibleNodeCount)} nœud{visibleNodeCount === 1 ? '' : 's'} visible{visibleNodeCount === 1 ? '' : 's'}</span>
                    </div>
                  </div>
                  <label className="graph-search">
                    <Icon name="search" size={15} />
                    <input
                      type="search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Rechercher un symbole ou fichier…"
                      aria-label="Rechercher un symbole ou fichier"
                    />
                    {query && (
                      <button type="button" aria-label="Effacer la recherche" onClick={() => setQuery('')}>
                        <Icon name="close" size={14} />
                      </button>
                    )}
                  </label>
                </div>

                <Suspense fallback={<div className="graph-loading"><span className="spinner" /> Préparation du graphe…</div>}>
                  <GraphCanvas
                    graph={graph}
                    activeNodeTypes={activeNodeTypes}
                    activeRelationTypes={activeRelationTypes}
                    query={query}
                    selectedNodeId={selectedNodeId}
                    visibleNodeCount={visibleNodeCount}
                    onSelectNode={setSelectedNodeId}
                  />
                </Suspense>

                <div className="graph-legend" aria-label="Légende des relations">
                  <span className="legend-caption">RELATIONS</span>
                  <LegendItem label="Appel" color={RELATION_PRESENTATION.CALLS.color} />
                  <LegendItem label="Import" color={RELATION_PRESENTATION.IMPORTS.color} />
                  <LegendItem label="Héritage" color={RELATION_PRESENTATION.EXTENDS.color} />
                  <LegendItem label="Structure" color={RELATION_PRESENTATION.DEFINES.color} />
                  <span className="legend-inferred"><i /> Inférence</span>
                </div>
              </section>

              <aside className="details-panel" aria-label="Détails de la sélection">
                {selectedNode ? (
                  <>
                    <div className="details-header">
                      <div>
                        <span className="panel-kicker">INSPECTEUR</span>
                        <strong>Détails du nœud</strong>
                      </div>
                      <button
                        className="icon-button"
                        type="button"
                        aria-label="Effacer la sélection"
                        title="Effacer la sélection"
                        onClick={() => setSelectedNodeId(null)}
                      >
                        <Icon name="close" size={15} />
                      </button>
                    </div>
                    <div className="details-content">
                      <div className="selected-identity">
                        <div
                          className="selected-type-icon"
                          style={{ color: NODE_PRESENTATION[selectedNode.type].color }}
                        >
                          <Icon name={NODE_PRESENTATION[selectedNode.type].icon} size={19} />
                        </div>
                        <span className="type-badge" style={{ color: NODE_PRESENTATION[selectedNode.type].color }}>
                          {formatNodeType(selectedNode.type)}
                        </span>
                        <h3>{selectedNode.name}</h3>
                        <span className="node-location">
                          {selectedNode.path || '.'}
                          {selectedNode.start_line ? `:${selectedNode.start_line}` : ''}
                        </span>
                        {Boolean(selectedNode.metadata.exported) && <span className="exported-badge">Exporté</span>}
                      </div>

                      <div className="detail-section">
                        <div className="detail-section-title">PROPRIÉTÉS</div>
                        <dl className="property-list">
                          <div>
                            <dt>Type de nœud</dt>
                            <dd>{formatNodeType(selectedNode.type)}</dd>
                          </div>
                          <div>
                            <dt>Fichier</dt>
                            <dd className="property-path">{selectedNode.path || '.'}</dd>
                          </div>
                          <div>
                            <dt>Ligne</dt>
                            <dd>{selectedNode.start_line ? `${selectedNode.start_line}${selectedNode.end_line && selectedNode.end_line !== selectedNode.start_line ? `–${selectedNode.end_line}` : ''}` : '—'}</dd>
                          </div>
                          {typeof selectedNode.metadata.language === 'string' && (
                            <div>
                              <dt>Langage</dt>
                              <dd>{selectedNode.metadata.language}</dd>
                            </div>
                          )}
                          {typeof selectedNode.metadata.qualified_name === 'string' && (
                            <div>
                              <dt>Nom qualifié</dt>
                              <dd>{selectedNode.metadata.qualified_name}</dd>
                            </div>
                          )}
                        </dl>
                        <div className="node-id-block">
                          <div className="node-id-heading">
                            <span>ID stable</span>
                            <button type="button" onClick={() => void handleCopyId()} title="Copier l’identifiant">
                              <Icon name={copied ? 'check' : 'copy'} size={13} />
                              {copied ? 'Copié' : 'Copier'}
                            </button>
                          </div>
                          <code>{selectedNode.id}</code>
                        </div>
                      </div>

                      <div className="detail-section relation-detail-section">
                        <div className="detail-section-title">
                          RELATIONS <span>{selectedRelations.length}</span>
                        </div>
                        {selectedRelations.length > 0 ? (
                          <div className="detail-relations">
                            {selectedRelations.slice(0, 24).map((relation) => (
                              <RelationRow
                                key={relation.id}
                                relation={relation}
                                selectedNode={selectedNode}
                                nodeById={nodeById}
                                onSelect={setSelectedNodeId}
                              />
                            ))}
                            {selectedRelations.length > 24 && (
                              <span className="more-relations">+ {selectedRelations.length - 24} autres relations</span>
                            )}
                          </div>
                        ) : (
                          <div className="detail-empty">
                            <Icon name="branch" size={17} />
                            <span>Aucune relation observée pour ce nœud.</span>
                          </div>
                        )}
                      </div>

                      {stats.issues > 0 && graph.metadata.issues.length > 0 && (
                        <div className="detail-section diagnostic-section">
                          <div className="detail-section-title"><Icon name="alert" size={13} /> DIAGNOSTICS DU PROJET</div>
                          {graph.metadata.issues.slice(0, 3).map((issue, index) => (
                            <div className="diagnostic-item" key={`${issue.path}-${issue.reason}-${index}`}>
                              <strong>{issue.reason.replaceAll('_', ' ')}</strong>
                              <span>{issue.path}{issue.line ? `:${issue.line}` : ''}</span>
                            </div>
                          ))}
                          {stats.issues > 3 && <span className="more-relations">+ {stats.issues - 3} autres</span>}
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="details-empty-state">
                    <div className="empty-detail-icon"><Icon name="activity" size={20} /></div>
                    <span className="panel-kicker">INSPECTEUR</span>
                    <strong>Sélectionnez un nœud</strong>
                    <p>Cliquez sur un élément du graphe ou un fichier pour consulter ses propriétés et ses relations.</p>
                  </div>
                )}
              </aside>
            </section>
          </>
        ) : (
          <section className="welcome-screen">
            <div className="welcome-orbit orbit-one" />
            <div className="welcome-orbit orbit-two" />
            <div className="welcome-content">
              <div className="welcome-visual">
                <BrandMark />
                <span className="visual-node visual-a" />
                <span className="visual-node visual-b" />
                <span className="visual-node visual-c" />
                <span className="visual-line visual-line-a" />
                <span className="visual-line visual-line-b" />
              </div>
              <div className="welcome-copy">
                <span className="welcome-eyebrow"><span /> ANALYSE STATIQUE · JAVASCRIPT & TYPESCRIPT</span>
                <h1>Votre code,<br /><span>mis en relation.</span></h1>
                <p>
                  Explorez les fichiers, symboles et dépendances de votre projet dans un graphe interactif.
                  L’analyse reste locale et n’exécute jamais votre code.
                </p>
              </div>
              <form className="welcome-form" onSubmit={handleSubmit}>
                <label htmlFor="welcome-project-path">Chemin du dossier du projet</label>
                <div className="welcome-input-wrap">
                  <Icon name="folder" size={18} />
                  <input
                    id="welcome-project-path"
                    value={projectPath}
                    onChange={(event) => setProjectPath(event.target.value)}
                    placeholder="Ex. : examples/demo-ts"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button className="analyze-button" type="submit" disabled={loading}>
                    {loading ? <span className="spinner" /> : <Icon name="scan" size={16} />}
                    {loading ? 'Analyse…' : 'Analyser le projet'}
                    {!loading && <Icon name="arrow-right" size={15} />}
                  </button>
                </div>
                <div className="welcome-form-footer">
                  <span>Racine autorisée par la configuration locale de l’API.</span>
                  <button type="button" onClick={() => void scanProject('examples/demo-ts')}>
                    <Icon name="spark" size={14} /> Essayer la démo incluse
                  </button>
                </div>
              </form>
              <div className="trust-row">
                <span><Icon name="lock" size={14} /> 100 % local</span>
                <i />
                <span><Icon name="shield" size={14} /> Aucun code exécuté</span>
                <i />
                <span><Icon name="activity" size={14} /> Tree-sitter</span>
              </div>
            </div>
            <div className="welcome-bottom-note">CODEGRAPH <span>·</span> CARTOGRAPHIE STATIQUE DE CODE</div>
          </section>
        )}
      </main>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: IconName
  label: string
  value: number
  accent: 'blue' | 'violet' | 'mint' | 'amber'
}) {
  return (
    <div className={`stat-card stat-${accent}`}>
      <span className="stat-icon"><Icon name={icon} size={15} /></span>
      <div>
        <span className="stat-value">{formatCount(value)}</span>
        <span className="stat-label">{label}</span>
      </div>
    </div>
  )
}

function LegendItem({ label, color }: { label: string; color: string }) {
  return (
    <span className="legend-item">
      <i style={{ backgroundColor: color }} />
      {label}
    </span>
  )
}

function RelationRow({
  relation,
  selectedNode,
  nodeById,
  onSelect,
}: {
  relation: GraphRelation
  selectedNode: GraphNode
  nodeById: Map<string, GraphNode>
  onSelect: (nodeId: string | null) => void
}) {
  const outgoing = relation.source === selectedNode.id
  const otherId = outgoing ? relation.target : relation.source
  const otherNode = nodeById.get(otherId)
  const relationPresentation = RELATION_PRESENTATION[relation.type]
  const confidence = Math.round(relation.confidence * 100)

  return (
    <button className="relation-row" type="button" onClick={() => onSelect(otherId)} title={otherId}>
      <span className="relation-direction" style={{ color: relationPresentation.color }}>
        <Icon name={outgoing ? 'arrow-right' : 'arrow-left'} size={14} />
      </span>
      <span className="relation-row-copy">
        <span className="relation-row-top">
          <strong style={{ color: relationPresentation.color }}>{relationLabel(relation.type)}</strong>
          <span>{relation.inferred ? 'Inférence' : 'Direct'}</span>
        </span>
        <span className="relation-target-name">{otherNode?.name ?? otherId}</span>
        <span className="relation-target-path">{otherNode?.path ?? relation.provenance.path}</span>
      </span>
      <span className="confidence-meter" title={`Confiance ${confidence} %`}>
        <i style={{ width: `${confidence}%`, backgroundColor: relationPresentation.color }} />
      </span>
    </button>
  )
}

export default App
