/** 对话会话与 SSE 流式聊天 API 模块 */

import request, { API_BASE_URL, refreshAccessToken } from './request'
import type { Conversation, Message, RagContext, RetrievalMode } from '../types'

/** RAG 检索参数设置 */
export interface RagSettings {
  rag_enabled: boolean
  knowledge_base_id: number | null
  retrieval_mode: RetrievalMode
  max_retrieval_tokens: number
}

/** 获取对话会话列表 */
export const getConversations = () => {
  return request.get<Conversation[]>('/chat/conversations')
}

/** 新建对话会话 */
export const createConversation = (data: {
  title: string
  model_name?: string
  knowledge_base_id?: number | null
  rag_enabled?: boolean
  retrieval_mode?: RetrievalMode
  max_retrieval_tokens?: number
}) => {
  return request.post<Conversation>('/chat/conversations', data)
}

/** 删除指定对话会话 */
export const deleteConversation = (id: number) => {
  return request.delete(`/chat/conversations/${id}`)
}

/** 获取会话历史消息记录 */
export const getMessages = (conversationId: number) => {
  return request.get<Message[]>(`/chat/conversations/${conversationId}/messages`)
}

/** 修改对话调用的 LLM 模型 */
export const updateModel = (conversationId: number, modelName: string) => {
  return request.put(`/chat/conversations/${conversationId}/model`, { model_name: modelName })
}

/** 修改对话的 RAG 检索配置 */
export const updateRagSettings = (conversationId: number, settings: RagSettings) => {
  return request.put(`/chat/conversations/${conversationId}/rag`, settings)
}

/**
 * 发送消息并接收 SSE 流式响应
 * @param {number} conversationId 会话 ID
 * @param {string} content 提问内容
 * @param {RagSettings} settings RAG 配置
 * @param {(chunk: string) => void} onChunk 文本增量回调
 * @param {(context: RagContext) => void} onRag RAG 检索元数据回调
 */
export const sendMessage = async (
  conversationId: number,
  content: string,
  settings: RagSettings,
  onChunk: (chunk: string) => void,
  onRag: (context: RagContext) => void
) => {
  const execute = (token: string | null) =>
    fetch(`${API_BASE_URL}/chat/conversations/${conversationId}/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token || ''}`
      },
      body: JSON.stringify({ content, ...settings })
    })

  let response = await execute(localStorage.getItem('token'))
  if (response.status === 401 && localStorage.getItem('refresh_token')) {
    response = await execute(await refreshAccessToken())
  }

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
    }
    let detail = '网络请求失败'
    try {
      const errorData = await response.json()
      if (typeof errorData.detail === 'string') detail = errorData.detail
    } catch {
      // 维持默认错误提示
    }
    throw new Error(detail)
  }

  if (!response.body) {
    throw new Error('未获取到数据流')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let streamFinished = false

  const processEvent = (eventBlock: string) => {
    const lines = eventBlock.split(/\r?\n/)
    const eventType = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const dataStr = lines
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
      .join('\n')

    if (!dataStr) return
    if (dataStr === '[DONE]') {
      streamFinished = true
      return
    }

    let data: { content?: string, message?: string } | RagContext
    try {
      data = JSON.parse(dataStr)
    } catch {
      throw new Error('流式响应格式错误')
    }

    if (eventType === 'error') {
      throw new Error('message' in data ? data.message || '模型调用失败' : '模型调用失败')
    }
    if (eventType === 'rag') {
      onRag(data as RagContext)
      return
    }
    if ('content' in data && data.content) onChunk(data.content)
  }

  try {
    while (!streamFinished) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })

      const events = buffer.split(/\r?\n\r?\n/)
      buffer = events.pop() || ''
      for (const eventBlock of events) {
        processEvent(eventBlock)
      }
      if (done) break
    }

    if (buffer.trim()) processEvent(buffer)
    if (!streamFinished) throw new Error('模型流意外中断')
  } finally {
    reader.releaseLock()
  }
}
