<!-- 单条聊天消息渲染组件：支持 Markdown 渲染、代码高亮以及 RAG 检索引用切片展开展示 -->
<template>
  <div class="message-wrapper" :class="{ 'is-user': isUser }">
    <div class="message-content" :class="{ 'glass-card': !isUser }">
      <div v-if="!isUser" class="avatar">
        <el-icon><Monitor /></el-icon>
      </div>
      <!-- RAG 检索上下文与引用文档折叠面板 -->
      <details v-if="message.rag_context?.enabled" class="rag-context">
        <summary>
          {{ modeLabel }} · {{ message.rag_context.sources.length }} 个切片 ·
          {{ message.rag_context.retrieved_tokens }} Token
        </summary>
        <div
          v-for="(source, index) in message.rag_context.sources"
          :key="source.id"
          class="rag-source"
        >
          <div class="source-title">
            [资料 {{ index + 1 }}] {{ source.document_name }} · 切片 {{ source.chunk_index }}
            · {{ source.token_count }} Token · 分数 {{ source.score.toFixed(4) }}
          </div>
          <div class="source-text">{{ source.text }}</div>
        </div>
      </details>
      <!-- 消息 Markdown 内容区 -->
      <div class="markdown-body" v-html="renderedContent"></div>
      <div class="timestamp">{{ timeText }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Message } from '../types'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import { Monitor } from '@element-plus/icons-vue'

const props = defineProps<{
  message: Message
}>()

// 判断消息发送者角色是否为当前用户
const isUser = computed(() => props.message.role === 'user')

// RAG 模式显示标签
const modeLabel = computed(() => {
  const labels = {
    semantic: '语义检索',
    dense: 'Dense 检索',
    hybrid: '混合检索'
  }
  return props.message.rag_context
    ? labels[props.message.rag_context.mode]
    : ''
})

// 初始化 Markdown 解析器与 highlight.js 代码高亮插件
const md = new MarkdownIt({
  highlight: function (str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch (__) {}
    }
    return ''
  }
})

// 计算解析后的 HTML 字符串
const renderedContent = computed(() => md.render(props.message.content))

// 格式化消息创建时间点
const timeText = computed(() => {
  const date = new Date(props.message.created_at)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
})
</script>

<style scoped>
.message-wrapper {
  display: flex;
  margin-bottom: 24px;
  width: 100%;
}

.message-wrapper.is-user {
  justify-content: flex-end;
}

.message-content {
  max-width: 80%;
  padding: 16px 20px;
  border-radius: var(--radius-lg);
  position: relative;
  animation: slideUp var(--transition-normal) forwards;
}

.message-wrapper.is-user .message-content {
  background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end));
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-wrapper:not(.is-user) .message-content {
  background: var(--bg-panel);
  border-bottom-left-radius: 4px;
  padding-left: 48px;
}

.avatar {
  position: absolute;
  left: 12px;
  top: 16px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-primary);
}

.timestamp {
  font-size: 11px;
  opacity: 0.78;
  margin-top: 8px;
  text-align: right;
}

.rag-context {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(139, 167, 255, 0.38);
  border-radius: 8px;
  background: rgba(112, 148, 255, 0.12);
  font-size: 12px;
}

.rag-context summary {
  cursor: pointer;
  color: var(--color-primary-strong);
}

.rag-source {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.source-title {
  color: var(--text-secondary);
  margin-bottom: 5px;
}

.source-text {
  white-space: pre-wrap;
  max-height: 120px;
  overflow: auto;
  line-height: 1.5;
}

::v-deep(.markdown-body) {
  color: inherit;
  font-size: 14px;
  line-height: 1.6;
}
::v-deep(.markdown-body p) { margin-bottom: 12px; }
::v-deep(.markdown-body pre) {
  background: #07101d;
  border: 1px solid var(--border-color);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
}
::v-deep(.markdown-body code) {
  font-family: monospace;
}
</style>
