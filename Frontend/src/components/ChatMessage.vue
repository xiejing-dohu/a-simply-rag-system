<template>
  <div class="message-wrapper" :class="{ 'is-user': isUser }">
    <div class="message-content" :class="{ 'glass-card': !isUser }">
      <div v-if="!isUser" class="avatar">
        <el-icon><Monitor /></el-icon>
      </div>
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

const isUser = computed(() => props.message.role === 'user')
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

const md = new MarkdownIt({
  highlight: function (str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch (__) {}
    }
    return '' // use external default escaping
  }
})

const renderedContent = computed(() => md.render(props.message.content))

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
  opacity: 0.6;
  margin-top: 8px;
  text-align: right;
}

.rag-context {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(102, 126, 234, 0.28);
  border-radius: 8px;
  background: rgba(102, 126, 234, 0.08);
  font-size: 12px;
}

.rag-context summary {
  cursor: pointer;
  color: var(--color-primary);
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

/* Markdown 样式简化 */
::v-deep(.markdown-body) {
  color: inherit;
  font-size: 14px;
  line-height: 1.6;
}
::v-deep(.markdown-body p) { margin-bottom: 12px; }
::v-deep(.markdown-body pre) {
  background: #1e1e1e;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
}
::v-deep(.markdown-body code) {
  font-family: monospace;
}
</style>
