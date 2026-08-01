/** 知识库、文档解析与 Milvus 探测 API 模块 */

import request from './request'
import type {
  EmbeddingConfig,
  DocumentTask,
  KnowledgeBase,
  KnowledgeDocument,
  MilvusChunkPage,
  MilvusSchema,
  VectorOperation
} from '../types'

/** 获取系统 Embedding 配置 */
export const getEmbeddingConfig = () => {
  return request.get<EmbeddingConfig>('/knowledge-bases/embedding-config')
}

/** 获取知识库列表 */
export const getKnowledgeBases = () => {
  return request.get<KnowledgeBase[]>('/knowledge-bases/')
}

/** 创建新知识库 */
export const createKnowledgeBase = (data: {
  name: string
  description?: string
  vector_dimension: number
}) => {
  return request.post<KnowledgeBase>('/knowledge-bases/', data)
}

/** 删除知识库 */
export const deleteKnowledgeBase = (id: number) => {
  return request.delete<{ status: string, operation: VectorOperation }>(
    `/knowledge-bases/${id}`
  )
}

/** 查询向量 Outbox 异步任务状态 */
export const getVectorOperation = (operationId: string) => {
  return request.get<VectorOperation>(`/knowledge-bases/operations/${operationId}`)
}

/** 上传文档并开始切片与向量化 */
export const uploadDocument = (
  kbId: number,
  file: File,
  chunkTokens: number,
  overlapTokens: number
) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('chunk_tokens', String(chunkTokens))
  formData.append('overlap_tokens', String(overlapTokens))
  return request.post<{ status: string, task: DocumentTask }>(
    `/knowledge-bases/${kbId}/documents/`,
    formData,
    { timeout: 60000 }
  )
}

/** 查询文档处理异步任务进度 */
export const getDocumentTask = (taskId: string) => {
  return request.get<DocumentTask>(`/knowledge-bases/tasks/${taskId}`)
}

/** 获取知识库已导入文档列表 */
export const getDocuments = (kbId: number) => {
  return request.get<KnowledgeDocument[]>(`/knowledge-bases/${kbId}/documents/`)
}

/** 探测获取 Milvus 集合的 Schema 字段信息 */
export const getMilvusSchema = (kbId: number) => {
  return request.get<MilvusSchema>(`/knowledge-bases/${kbId}/milvus/schema`)
}

/** 分页游标获取 Milvus 存储的向量切片记录 */
export const getMilvusChunks = (
  kbId: number,
  offset = 0,
  limit = 50,
  cursor: number | null = null
) => {
  return request.get<MilvusChunkPage>(`/knowledge-bases/${kbId}/milvus/chunks`, {
    params: { offset, limit, ...(cursor === null ? {} : { cursor }) },
    timeout: 30000
  })
}
