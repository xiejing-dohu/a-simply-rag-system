/** 对话会话、消息与 RAG 检索上下文的 TypeScript 接口类型定义 */

/** 检索模式："semantic" (向量语义) | "dense" (余弦相似度) | "hybrid" (混合检索) */
export type RetrievalMode = 'semantic' | 'dense' | 'hybrid'

/** 对话会话实体接口 */
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

/** RAG 引用的单条文档切片来源 */
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

/** RAG 检索结果上下文 */
export interface RagContext {
  enabled: boolean
  knowledge_base_id: number
  mode: RetrievalMode
  retrieved_tokens: number
  sources: RagSource[]
}

/** 对话消息实体接口 */
export interface Message {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  rag_context?: RagContext | null
}
