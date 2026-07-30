// 用户相关
export interface User {
  id: number
  username: string
  email: string
  role: 'admin' | 'employee'
  is_root_admin: boolean
  is_active: boolean
  created_at: string
  five_hour_token_limit: number | null
  weekly_token_limit: number | null
  five_hour_tokens_used: number
  weekly_tokens_used: number
  input_tokens_used: number
  output_tokens_used: number
  total_tokens_used: number
  five_hour_window_started_at: string
  weekly_window_started_at: string
  five_hour_resets_at: string
  weekly_resets_at: string
}

export interface LoginForm {
  username: string
  password: string
}

export interface RegisterForm {
  username: string
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}

// 会话相关
export interface Conversation {
  id: number
  title: string
  model_name: string
  knowledge_base_id: number | null
  rag_enabled: boolean
  retrieval_mode: RetrievalMode
  max_retrieval_tokens: number
  created_at: string
  updated_at: string
}

export type RetrievalMode = 'semantic' | 'dense' | 'hybrid'

export interface RagSource {
  id: number
  text: string
  document_name: string
  source_type: string
  chunk_index: number
  token_count: number
  score: number
  created_at: string
  truncated?: boolean
}

export interface RagContext {
  enabled: boolean
  knowledge_base_id: number
  mode: RetrievalMode
  retrieved_tokens: number
  sources: RagSource[]
}

export interface Message {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  rag_context?: RagContext | null
}

// 知识库
export interface KnowledgeBase {
  id: number
  name: string
  description: string
  collection_name: string
  embedding_model: string
  vector_dimension: number
  file_count: number
  chunk_count: number
  created_by: number
  created_at: string
}

export interface EmbeddingConfig {
  model: string
  provider: string
  supported_dimensions: number[]
  default_dimension: number
  supported_extensions: string[]
}

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

export type DocumentTaskStatus = 'queued' | 'processing' | 'completed' | 'failed'

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

export interface MilvusField {
  name: string
  type: string
  is_primary: boolean
  auto_id: boolean
  dimension: number | null
  max_length: number | null
}

export interface MilvusSchema {
  collection_name: string
  description: string
  entity_count: number
  fields: MilvusField[]
  indexes: Record<string, unknown>[]
}

export interface MilvusChunk {
  id: number
  text: string
  document_name: string
  source_type: string
  chunk_index: number
  token_count: number
  uploaded_by: number
  created_at: string
}

export interface MilvusChunkPage {
  items: MilvusChunk[]
  offset: number
  limit: number
  total: number
  next_cursor: number | null
}

// 模型
export interface ModelInfo {
  id: string
  name: string
  description: string
  provider: string
}
