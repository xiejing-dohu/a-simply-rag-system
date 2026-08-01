/** 对话、历史消息列表与 RAG 检索参数 Pinia 状态管理模块 */

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
  // 对话会话列表
  const conversations = ref<Conversation[]>([])
  // 当前激活的会话对象
  const currentConversation = ref<Conversation | null>(null)
  // 当前激活会话的历史消息列表
  const messages = ref<Message[]>([])
  // 当前选中的 LLM 模型 ID
  const currentModel = ref<string>('')
  // 当前关联选中的知识库 ID
  const currentKnowledgeBase = ref<number | null>(null)
  // 是否开启 RAG 检索增强
  const ragEnabled = ref(false)
  // 检索模式 ("semantic" | "dense" | "hybrid")
  const retrievalMode = ref<RetrievalMode>('semantic')
  // 最大检索上下文 Token 限制
  const maxRetrievalTokens = ref(2048)
  // 是否正在流式接收模型生成文本
  const isStreaming = ref(false)

  /** 加载用户所有对话会话 */
  const fetchConversations = async () => {
    const res = await getConversations()
    conversations.value = res.data
  }

  /** 创建新的对话会话 */
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

  /** 删除指定对话 */
  const deleteConversationAction = async (id: number) => {
    await deleteConversation(id)
    conversations.value = conversations.value.filter(c => c.id !== id)
    if (currentConversation.value?.id === id) {
      currentConversation.value = null
      messages.value = []
    }
  }

  /** 获取某个会话下的历史消息记录 */
  const fetchMessages = async (id: number) => {
    const res = await getMessages(id)
    messages.value = res.data
  }

  /** 切换使用的大语言模型 */
  const switchModel = async (conversationId: number, modelName: string) => {
    await updateModel(conversationId, modelName)
    currentModel.value = modelName
    const conv = conversations.value.find(c => c.id === conversationId)
    if (conv) conv.model_name = modelName
  }

  /** 载入会话关联的 RAG 配置 */
  const loadConversationSettings = (conversation: Conversation) => {
    currentKnowledgeBase.value = conversation.knowledge_base_id
    ragEnabled.value = conversation.rag_enabled
    retrievalMode.value = conversation.retrieval_mode
    maxRetrievalTokens.value = conversation.max_retrieval_tokens
  }

  /** 保存并更新当前会话的 RAG 配置 */
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

  /** 发送消息并渲染 SSE 实时打字效果 */
  const sendMessageAction = async (content: string) => {
    if (!currentConversation.value) return

    // 先在界面追加用户消息
    const tempId = Date.now()
    messages.value.push({
      id: tempId,
      conversation_id: currentConversation.value.id,
      role: 'user',
      content,
      created_at: new Date().toISOString()
    })

    // 追加 AI 占位消息
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
