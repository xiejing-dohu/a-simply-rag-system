import request, { API_BASE_URL } from './request'
import type { Conversation, Message, RagContext, RetrievalMode } from '../types'

export interface RagSettings {
  rag_enabled: boolean
  knowledge_base_id: number | null
  retrieval_mode: RetrievalMode
  max_retrieval_tokens: number
}

export const getConversations = () => {
  return request.get<Conversation[]>('/chat/conversations')
}

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

export const deleteConversation = (id: number) => {
  return request.delete(`/chat/conversations/${id}`)
}

export const getMessages = (conversationId: number) => {
  return request.get<Message[]>(`/chat/conversations/${conversationId}/messages`)
}

export const updateModel = (conversationId: number, modelName: string) => {
  return request.put(`/chat/conversations/${conversationId}/model`, { model_name: modelName })
}

export const updateRagSettings = (conversationId: number, settings: RagSettings) => {
  return request.put(`/chat/conversations/${conversationId}/rag`, settings)
}

// 使用 fetch + ReadableStream 处理 SSE
export const sendMessage = async (
  conversationId: number,
  content: string,
  settings: RagSettings,
  onChunk: (chunk: string) => void,
  onRag: (context: RagContext) => void
) => {
  const token = localStorage.getItem('token')
  const response = await fetch(`${API_BASE_URL}/chat/conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ content, ...settings })
  })

  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = '/login'
    }
    let detail = '网络请求失败'
    try {
      const errorData = await response.json()
      if (typeof errorData.detail === 'string') detail = errorData.detail
    } catch {
      // Keep the generic error when the response is not JSON.
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
