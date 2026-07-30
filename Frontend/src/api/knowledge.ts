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

export const getEmbeddingConfig = () => {
  return request.get<EmbeddingConfig>('/knowledge-bases/embedding-config')
}

export const getKnowledgeBases = () => {
  return request.get<KnowledgeBase[]>('/knowledge-bases/')
}

export const createKnowledgeBase = (data: {
  name: string
  description?: string
  vector_dimension: number
}) => {
  return request.post<KnowledgeBase>('/knowledge-bases/', data)
}

export const deleteKnowledgeBase = (id: number) => {
  return request.delete<{ status: string, operation: VectorOperation }>(
    `/knowledge-bases/${id}`
  )
}

export const getVectorOperation = (operationId: string) => {
  return request.get<VectorOperation>(`/knowledge-bases/operations/${operationId}`)
}

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

export const getDocumentTask = (taskId: string) => {
  return request.get<DocumentTask>(`/knowledge-bases/tasks/${taskId}`)
}

export const getDocuments = (kbId: number) => {
  return request.get<KnowledgeDocument[]>(`/knowledge-bases/${kbId}/documents/`)
}

export const getMilvusSchema = (kbId: number) => {
  return request.get<MilvusSchema>(`/knowledge-bases/${kbId}/milvus/schema`)
}

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
