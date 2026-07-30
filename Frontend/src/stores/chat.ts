import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getConversations,
  createConversation,
  deleteConversation,
  getMessages,
  sendMessage,
  updateModel,
  updateRagSettings
} from '../api/chat'
import { getModels } from '../api/model'
import { useAuthStore } from './auth'
import type { Conversation, Message, RetrievalMode } from '../types'

export const useChatStore = defineStore('chat', () => {
  const authStore = useAuthStore()
  const conversations = ref<Conversation[]>([])
  const currentConversation = ref<Conversation | null>(null)
  const messages = ref<Message[]>([])
  const currentModel = ref<string>('')
  const currentKnowledgeBase = ref<number | null>(null)
  const ragEnabled = ref(false)
  const retrievalMode = ref<RetrievalMode>('semantic')
  const maxRetrievalTokens = ref(2048)
  const isStreaming = ref(false)

  const fetchConversations = async () => {
    const res = await getConversations()
    conversations.value = res.data
  }

  const createConversationAction = async (title: string) => {
    if (!currentModel.value) {
      const modelResponse = await getModels()
      currentModel.value = modelResponse.data[0]?.id || ''
    }
    const res = await createConversation({
      title,
      model_name: currentModel.value,
      knowledge_base_id: currentKnowledgeBase.value,
      rag_enabled: ragEnabled.value,
      retrieval_mode: retrievalMode.value,
      max_retrieval_tokens: maxRetrievalTokens.value
    })
    conversations.value.unshift(res.data)
    currentConversation.value = res.data
    messages.value = []
    return res.data
  }

  const deleteConversationAction = async (id: number) => {
    await deleteConversation(id)
    conversations.value = conversations.value.filter(c => c.id !== id)
    if (currentConversation.value?.id === id) {
      currentConversation.value = null
      messages.value = []
    }
  }

  const fetchMessages = async (id: number) => {
    const res = await getMessages(id)
    messages.value = res.data
  }

  const switchModel = async (conversationId: number, modelName: string) => {
    await updateModel(conversationId, modelName)
    currentModel.value = modelName
    const conv = conversations.value.find(c => c.id === conversationId)
    if (conv) conv.model_name = modelName
  }

  const loadConversationSettings = (conversation: Conversation) => {
    currentKnowledgeBase.value = conversation.knowledge_base_id
    ragEnabled.value = conversation.rag_enabled
    retrievalMode.value = conversation.retrieval_mode
    maxRetrievalTokens.value = conversation.max_retrieval_tokens
  }

  const saveRagSettings = async () => {
    if (!currentConversation.value) return
    await updateRagSettings(currentConversation.value.id, {
      rag_enabled: ragEnabled.value,
      knowledge_base_id: currentKnowledgeBase.value,
      retrieval_mode: retrievalMode.value,
      max_retrieval_tokens: maxRetrievalTokens.value
    })
    Object.assign(currentConversation.value, {
      rag_enabled: ragEnabled.value,
      knowledge_base_id: currentKnowledgeBase.value,
      retrieval_mode: retrievalMode.value,
      max_retrieval_tokens: maxRetrievalTokens.value
    })
  }

  const sendMessageAction = async (content: string) => {
    if (!currentConversation.value) return

    // 添加用户消息
    const tempId = Date.now()
    messages.value.push({
      id: tempId,
      conversation_id: currentConversation.value.id,
      role: 'user',
      content,
      created_at: new Date().toISOString()
    })

    // 添加 AI 占位消息
    const aiMessageId = tempId + 1
    const aiMessage: Message = {
      id: aiMessageId,
      conversation_id: currentConversation.value.id,
      role: 'assistant' as const,
      content: '',
      created_at: new Date().toISOString()
    }
    messages.value.push(aiMessage)
    const aiMessageIndex = messages.value.length - 1

    isStreaming.value = true
    try {
      await sendMessage(
        currentConversation.value.id,
        content,
        {
          rag_enabled: ragEnabled.value,
          knowledge_base_id: currentKnowledgeBase.value,
          retrieval_mode: retrievalMode.value,
          max_retrieval_tokens: maxRetrievalTokens.value
        },
        (chunk: string) => {
          messages.value[aiMessageIndex].content += chunk
        },
        context => {
          messages.value[aiMessageIndex].rag_context = context
        }
      )
    } catch (e) {
      const message = e instanceof Error ? e.message : '未知错误'
      messages.value[aiMessageIndex].content += `\n[${message}]`
    } finally {
      isStreaming.value = false
      await authStore.fetchUser()
    }
  }

  return {
    conversations,
    currentConversation,
    messages,
    currentModel,
    currentKnowledgeBase,
    ragEnabled,
    retrievalMode,
    maxRetrievalTokens,
    isStreaming,
    fetchConversations,
    createConversation: createConversationAction,
    deleteConversation: deleteConversationAction,
    fetchMessages,
    sendMessage: sendMessageAction,
    switchModel,
    loadConversationSettings,
    saveRagSettings
  }
})
