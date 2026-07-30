import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  getEmbeddingConfig,
  getKnowledgeBases,
  getMilvusChunks,
  getMilvusSchema,
  uploadDocument
} from '../api/knowledge'
import type {
  EmbeddingConfig,
  KnowledgeBase,
  KnowledgeDocument,
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
    knowledgeBases.value.push(res.data)
  }

  const deleteKnowledgeBaseAction = async (id: number) => {
    await deleteKnowledgeBase(id)
    knowledgeBases.value = knowledgeBases.value.filter(kb => kb.id !== id)
  }

  const uploadDocumentAction = async (
    kbId: number,
    file: File,
    chunkTokens: number,
    overlapTokens: number
  ): Promise<KnowledgeDocument> => {
    const res = await uploadDocument(kbId, file, chunkTokens, overlapTokens)
    return res.data.document
  }

  const fetchMilvusSchema = async (kbId: number): Promise<MilvusSchema> => {
    const res = await getMilvusSchema(kbId)
    return res.data
  }

  const fetchMilvusChunks = async (
    kbId: number,
    offset = 0,
    limit = 50
  ): Promise<MilvusChunkPage> => {
    const res = await getMilvusChunks(kbId, offset, limit)
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
    fetchMilvusSchema,
    fetchMilvusChunks
  }
})