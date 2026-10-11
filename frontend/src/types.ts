export type NodeType =
  | 'project'
  | 'file'
  | 'function'
  | 'class'
  | 'interface'
  | 'type'
  | 'module'

export type RelationType =
  | 'CONTAINS'
  | 'IMPORTS'
  | 'DEFINES'
  | 'CALLS'
  | 'EXTENDS'
  | 'IMPLEMENTS'

export interface GraphNode {
  id: string
  type: NodeType
  name: string
  path: string
  start_line: number | null
  end_line: number | null
  metadata: Record<string, unknown>
}

export interface RelationProvenance {
  path: string
  start_line: number | null
  end_line: number | null
  evidence: string
  method: string
}

export interface GraphRelation {
  id: string
  source: string
  target: string
  type: RelationType
  provenance: RelationProvenance
  confidence: number
  certainty: 'direct' | 'high' | 'medium' | 'low'
  origin: 'direct' | 'inferred'
  inferred: boolean
}

export interface AnalysisIssue {
  path: string
  reason: string
  message: string
  line: number | null
}

export interface GraphMetadata {
  tool: string
  tool_version: string
  project_root: string
  project_path?: string
  project_id?: string
  discovered_files: number
  analyzed_files: number
  max_file_size_bytes: number
  languages: Record<string, number>
  imports_total: number
  imports_resolved: number
  calls_total: number
  calls_resolved: number
  inheritance_total: number
  inheritance_resolved: number
  unresolved_imports: Array<{
    path: string
    line: number
    specifier: string
    reason?: string
  }>
  unresolved_calls: Array<{
    path: string
    line: number
    callee: string
    reason?: string
  }>
  issues: AnalysisIssue[]
  node_count: number
  relation_count: number
}

export interface GraphDocument {
  schema_version: string
  metadata: GraphMetadata
  nodes: GraphNode[]
  relations: GraphRelation[]
}

export interface ProjectStats {
  schema_version: string
  project: string
  files: number
  symbols: number
  nodes: number
  relations: number
  nodes_by_type: Record<NodeType, number>
  relations_by_type: Partial<Record<RelationType, number>>
  imports: { total: number; resolved: number }
  calls: { total: number; resolved: number }
  inheritance: { total: number; resolved: number }
  issues: number
  max_file_size_bytes: number
}

export interface ScanResponse {
  project_id: string
  stats: ProjectStats
}

export interface HealthResponse {
  status: string
  schema_version: string
}
