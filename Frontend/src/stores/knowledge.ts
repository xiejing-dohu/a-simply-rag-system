import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  getEmbeddingConfig,
  getDocumentTask,
  getKnowledgeBases,
  getVectorOperation,
  getMilvusChunks,
  getMilvusSchema,
  uploadDocument
} from '../api/knowledge'
import type {
  EmbeddingConfig,
  DocumentTask,
  KnowledgeBase,
  MilvusChunkPage,
  MilvusSchema
} from '../types'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const knowledgeBases = ref<KnowledgeBase[]>([])
  const embeddingConfig = ref<EmbeddingConfig | null>(null)

  const fetchEmbeddingConfig = async () => {
    const res = await getEmbeddingConfig()
    embeddingConfig.value = res.data
  }

  const fetchKnowledgeBases = async () => {
    const res = await getKnowledgeBases()
    knowledgeBases.value = res.data
  }

  const createKnowledgeBaseAction = async (
    name: string,
    description: string,
    vectorDimension: number
  ) => {
    const res = await createKnowledgeBase({
      name,
      description,
      vector_dimension: vectorDimension
    })
    knowledgeBases.value.unshift(res.data)
    for (let attempt = 0; attempt < 75; attempt++) {
      if (res.data.status === 'active') return true
      if (res.data.status === 'create_failed') {
        throw new Error('Milvus 集合创建失败，请重试创建')
      }
      await new Promise(resolve => window.setTimeout(resolve, 800))
      await fetchKnowledgeBases()
      const current = knowledgeBases.value.find(item => item.id === res.data.id)
      if (!current) throw new Error('知识库创建记录不存在')
      res.data.status = current.status
    }
    return false
  }

  const deleteKnowledgeBaseAction = async (id: number) => {
    const response = await deleteKnowledgeBase(id)
    await fetchKnowledgeBases()
    let operation = response.data.operation
    for (let attempt = 0; attempt < 75; attempt++) {
      if (operation.status === 'completed' || operation.status === 'failed') break
      await new Promise(resolve => window.setTimeout(resolve, 800))
      operation = (await getVectorOperation(operation.id)).data
    }
    if (operation.status === 'failed') {
      await fetchKnowledgeBases()
      throw new Error(operation.error || 'Milvus 集合删除失败，可点击删除重新提交')
    }
    if (operation.status !== 'completed') {
      await fetchKnowledgeBases()
      return false
    }
    knowledgeBases.value = knowledgeBases.value.filter(kb => kb.id !== id)
    return true
  }

  const uploadDocumentAction = async (
    kbId: number,
    file: File,
    chunkTokens: number,
    overlapTokens: number
  ): Promise<DocumentTask> => {
    const res = await uploadDocument(kbId, file, chunkTokens, overlapTokens)
    return res.data.task
  }

  const fetchDocumentTask = async (taskId: string): Promise<DocumentTask> => {
    const res = await getDocumentTask(taskId)
    return res.data
  }

  const fetchMilvusSchema = async (kbId: number): Promise<MilvusSchema> => {
    const res = await getMilvusSchema(kbId)
    return res.data
  }

  const fetchMilvusChunks = async (
    kbId: number,
    offset = 0,
    limit = 50,
    cursor: number | null = null
  ): Promise<MilvusChunkPage> => {
    const res = await getMilvusChunks(kbId, offset, limit, cursor)
    return res.data
  }

  return {
    knowledgeBases,
    embeddingConfig,
    fetchEmbeddingConfig,
    fetchKnowledgeBases,
    createKnowledgeBase: createKnowledgeBaseAction,
    deleteKnowledgeBase: deleteKnowledgeBaseAction,
    uploadDocument: uploadDocumentAction,
    fetchDocumentTask,
    fetchMilvusSchema,
    fetchMilvusChunks
  }
})
