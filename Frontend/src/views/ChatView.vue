<!-- 智能聊天对话主页面组件：包含侧边会话切换、模型与 RAG 参数调节、打字机流式聊天界面 -->
<template>
  <div class="chat-container">
    <!-- 左侧会话列表 -->
    <aside class="sidebar glass-card">
      <div class="sidebar-header">
        <el-button type="primary" class="new-chat-btn" @click="handleNewChat">
          <el-icon><Plus /></el-icon> 新建会话
        </el-button>
      </div>
      <div class="conversation-list">
        <div 
          v-for="conv in chatStore.conversations" 
          :key="conv.id"
          class="conv-item"
          :class="{ active: chatStore.currentConversation?.id === conv.id }"
          @click="selectConversation(conv)"
        >
          <div class="conv-title">
            <el-icon><ChatDotRound /></el-icon>
            {{ conv.title }}
          </div>
          <el-button 
            type="danger" 
            link 
            class="delete-btn"
            @click.stop="handleDeleteChat(conv.id)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
    </aside>

    <!-- 主体聊天区域 -->
    <main class="chat-main">
      <header class="chat-header glass-card">
        <div class="header-left">
          <h2>{{ chatStore.currentConversation?.title || '未选择会话' }}</h2>
        </div>
        <div class="header-right" v-if="chatStore.currentConversation">
          <!-- 模型选择器 -->
          <ModelSelector />
        </div>
      </header>

      <!-- RAG 检索配置栏 -->
      <section v-if="chatStore.currentConversation" class="rag-settings glass-card">
        <div class="rag-switch">
          <span>启用 RAG</span>
          <el-switch v-model="chatStore.ragEnabled" />
        </div>
        <el-select
          v-model="chatStore.currentKnowledgeBase"
          placeholder="选择知识库"
          clearable
          :disabled="!chatStore.ragEnabled"
          class="kb-selector"
        >
          <el-option
            v-for="kb in activeKnowledgeBases"
            :key="kb.id"
            :label="`${kb.name} · ${kb.chunk_count} 切片`"
            :value="kb.id"
          />
        </el-select>
        <el-radio-group v-model="chatStore.retrievalMode" :disabled="!chatStore.ragEnabled" size="small">
          <el-tooltip content="Dense 候选后使用 MMR 去重，覆盖更多不同语义">
            <el-radio-button value="semantic">语义检索</el-radio-button>
          </el-tooltip>
          <el-tooltip content="按 Milvus COSINE 相似度直接排序">
            <el-radio-button value="dense">Dense 检索</el-radio-button>
          </el-tooltip>
          <el-tooltip content="Dense 与 BM25 关键词排名融合">
            <el-radio-button value="hybrid">混合检索</el-radio-button>
          </el-tooltip>
        </el-radio-group>
        <div class="token-budget">
          <span>最大召回 Token</span>
          <el-input-number
            v-model="chatStore.maxRetrievalTokens"
            :min="128"
            :max="16000"
            :step="256"
            :disabled="!chatStore.ragEnabled"
            controls-position="right"
          />
        </div>
        <el-button
          size="small"
          :loading="savingRag"
          :disabled="chatStore.ragEnabled && !chatStore.currentKnowledgeBase"
          @click="saveRagSettings"
        >
          应用设置
        </el-button>
      </section>

      <!-- 消息列表滚动区域 -->
      <div class="messages-area" ref="messagesArea">
        <div v-if="!chatStore.currentConversation" class="empty-state fade-in">
          <div class="icon-wrapper">
            <el-icon><ChatSquare /></el-icon>
          </div>
          <h3>欢迎使用智能 RAG 系统</h3>
          <p>请在左侧选择或新建一个会话开始聊天</p>
        </div>
        <template v-else>
          <ChatMessage 
            v-for="msg in chatStore.messages" 
            :key="msg.id" 
            :message="msg" 
          />
        </template>
      </div>

      <!-- 底部输入框 -->
      <div class="input-area" v-if="chatStore.currentConversation">
        <div class="input-wrapper glass-card">
          <el-input
            v-model="inputMsg"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            placeholder="输入您的问题 (Shift + Enter 换行，Enter 发送)..."
            @keydown.enter.prevent="handleEnter"
            :disabled="chatStore.isStreaming"
          />
          <el-button 
            type="primary" 
            class="send-btn" 
            :loading="chatStore.isStreaming"
            @click="sendMsg"
          >
            <el-icon><Position /></el-icon>
          </el-button>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import { useKnowledgeStore } from '../stores/knowledge'
import type { Conversation } from '../types'
import { Plus, ChatDotRound, Delete, ChatSquare, Position } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ChatMessage from '../components/ChatMessage.vue'
import ModelSelector from '../components/ModelSelector.vue'

const chatStore = useChatStore()
const kbStore = useKnowledgeStore()
const inputMsg = ref('')
const messagesArea = ref<HTMLElement | null>(null)
const savingRag = ref(false)

// 过滤状态为 active 可用的知识库列表
const activeKnowledgeBases = computed(() =>
  kbStore.knowledgeBases.filter(item => item.status === 'active')
)

onMounted(() => {
  chatStore.fetchConversations()
  kbStore.fetchKnowledgeBases()
})

/** 新建会话 */
const handleNewChat = async () => {
  if (chatStore.ragEnabled && !chatStore.currentKnowledgeBase) {
    return ElMessage.warning('启用 RAG 前请选择知识库')
  }
  await chatStore.createConversation('新对话 ' + new Date().toLocaleString())
}

/** 切换激活的会话 */
const selectConversation = async (conv: Conversation) => {
  chatStore.currentConversation = conv
  chatStore.currentModel = conv.model_name
  chatStore.loadConversationSettings(conv)
  await chatStore.fetchMessages(conv.id)
  scrollToBottom()
}

/** 删除会话 */
const handleDeleteChat = async (id: number) => {
  await chatStore.deleteConversation(id)
}

/** 回车键发送事件触发 */
const handleEnter = (e: KeyboardEvent) => {
  if (e.shiftKey) return
  sendMsg()
}

/** 发送提问消息 */
const sendMsg = async () => {
  if (!inputMsg.value.trim() || chatStore.isStreaming) return
  if (chatStore.ragEnabled && !chatStore.currentKnowledgeBase) {
    return ElMessage.warning('启用 RAG 前请选择知识库')
  }
  const msg = inputMsg.value
  inputMsg.value = ''
  scrollToBottom()
  await chatStore.sendMessage(msg)
}

/** 保存与更新当前会话的 RAG 参数 */
const saveRagSettings = async () => {
  savingRag.value = true
  try {
    await chatStore.saveRagSettings()
    ElMessage.success(chatStore.ragEnabled ? 'RAG 设置已应用' : 'RAG 已关闭')
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || 'RAG 设置保存失败')
  } finally {
    savingRag.value = false
  }
}

/** 自动滚动到消息区域底部 */
const scrollToBottom = async () => {
  await nextTick()
  if (messagesArea.value) {
    messagesArea.value.scrollTop = messagesArea.value.scrollHeight
  }
}

// 监听消息长度变化及流式打印过程中的增量自动底端对齐
watch(() => chatStore.messages.length, scrollToBottom)
watch(() => chatStore.messages[chatStore.messages.length - 1]?.content, () => {
  if (chatStore.isStreaming) {
    scrollToBottom()
  }
})
</script>

<style scoped>
.chat-container {
  display: flex;
  height: 100%;
  background: var(--bg-dark);
}

.sidebar {
  width: 260px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  border-radius: 0;
  border-top: none;
  border-bottom: none;
  border-left: none;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.new-chat-btn {
  width: 100%;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition-fast);
  margin-bottom: 8px;
  color: var(--text-secondary);
}

.conv-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.conv-item.active {
  background: var(--bg-active);
  color: var(--color-primary-strong);
}

.conv-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 14px;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.conv-item:hover .delete-btn {
  opacity: 1;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
}

.chat-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-radius: 0;
  border-top: none;
  border-left: none;
  border-right: none;
}

.header-left h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.header-right {
  display: flex;
  gap: 16px;
}

.rag-settings {
  min-height: 62px;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  gap: 14px;
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
}

.rag-switch,
.token-budget {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  white-space: nowrap;
}

.kb-selector {
  width: 220px;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
}

.empty-state {
  margin: auto;
  text-align: center;
  color: var(--text-secondary);
}

.icon-wrapper {
  font-size: 48px;
  color: var(--color-primary);
  margin-bottom: 16px;
  opacity: 0.8;
}

.empty-state h3 {
  color: var(--text-primary);
  margin-bottom: 8px;
  font-size: 20px;
}

.input-area {
  padding: 24px;
  background: linear-gradient(to top, var(--bg-dark) 50%, transparent);
}

.input-wrapper {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px;
}

::v-deep(.el-textarea__inner) {
  background: transparent !important;
  box-shadow: none !important;
  border: none !important;
  color: var(--text-primary);
  padding: 0;
  font-size: 14px;
  line-height: 1.5;
}

.send-btn {
  height: 40px;
  width: 40px;
  border-radius: 50%;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}
</style>
