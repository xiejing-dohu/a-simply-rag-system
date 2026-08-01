/** 知识库、文档解析任务及 Milvus 索引探测的 TypeScript 接口定义 */

/** 知识库实体接口 */
export interface KnowledgeBase {
  id: number
  name: string
  description: string
  collection_name: string
  embedding_model: string
  vector_dimension: number
  file_count: number
  chunk_count: number
  status: 'creating' | 'active' | 'deleting' | 'create_failed' | 'delete_failed' | 'inconsistent'
  generation: number
  created_by: number
  created_at: string
}

/** 向量异步 Outbox 操作实实体 */
export interface VectorOperation {
  id: string
  operation_type: 'create_collection' | 'drop_collection'
  resource_id: number
  status: 'pending' | 'processing' | 'retry' | 'completed' | 'failed' | 'cancelled'
  attempts: number
  max_attempts: number
  error: string | null
  created_at: string
  completed_at: string | null
}

/** 系统 Embedding 模型配置 */
export interface EmbeddingConfig {
  model: string
  provider: string
  supported_dimensions: number[]
  default_dimension: number
  supported_extensions: string[]
}

/** 知识库已导入文档实体 */
export interface KnowledgeDocument {
  id: number
  name: string
  size: number
  source_type: string
  chunk_tokens: number
  overlap_tokens: number
  chunk_count: number
  total_tokens: number
  vector_dimension: number
  embedding_model: string
  created_at: string
}

/** 文档处理异步任务状态 */
export type DocumentTaskStatus = 'queued' | 'processing' | 'completed' | 'failed'

/** 文档处理任务实体 */
export interface DocumentTask {
  id: string
  knowledge_base_id: number
  file_name: string
  file_size: number
  chunk_tokens: number
  overlap_tokens: number
  status: DocumentTaskStatus
  stage: string
  progress: number
  result_document_id: number | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** Milvus 字段元数据描述 */
export interface MilvusField {
  name: string
  type: string
  is_primary: boolean
  auto_id: boolean
  dimension: number | null
  max_length: number | null
}

/** Milvus Collection Schema 元数据 */
export interface MilvusSchema {
  collection_name: string
  description: string
  entity_count: number
  fields: MilvusField[]
  indexes: Record<string, unknown>[]
}

/** Milvus 单个切片实体数据 */
export interface MilvusChunk {
  id: number
  document_id?: string
  text: string
  document_name: string
  source_type: string
  chunk_index: number
  token_count: number
  uploaded_by: number
  created_at: string
}

/** Milvus 切片分页结果集 */
export interface MilvusChunkPage {
  items: MilvusChunk[]
  offset: number
  limit: number
  total: number
  next_cursor: number | null
}
