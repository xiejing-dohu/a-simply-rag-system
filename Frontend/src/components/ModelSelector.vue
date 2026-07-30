<template>
  <el-select
    v-model="selectedModel"
    class="model-selector"
    placeholder="选择模型"
    filterable
    @change="handleChange"
  >
    <el-option
      v-for="model in models"
      :key="model.id"
      :label="model.name"
      :value="model.id"
    >
      <div class="option-content">
        <span class="model-name">{{ model.name }}</span>
        <span class="model-provider">{{ model.provider }}</span>
      </div>
    </el-option>
  </el-select>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getModels } from '../api/model'
import type { ModelInfo } from '../types'
import { useChatStore } from '../stores/chat'

const models = ref<ModelInfo[]>([])
const chatStore = useChatStore()
const selectedModel = ref(chatStore.currentModel)

onMounted(async () => {
  try {
    const res = await getModels()
    models.value = res.data
    if (!models.value.some(model => model.id === chatStore.currentModel)) {
      const firstModel = models.value[0]?.id
      if (firstModel) {
        selectedModel.value = firstModel
        if (chatStore.currentConversation) {
          await chatStore.switchModel(chatStore.currentConversation.id, firstModel)
        } else {
          chatStore.currentModel = firstModel
        }
      }
    } else {
      selectedModel.value = chatStore.currentModel
    }
  } catch (e) {
    models.value = []
  }
})

const handleChange = (val: string) => {
  if (chatStore.currentConversation) {
    chatStore.switchModel(chatStore.currentConversation.id, val)
  }
}
</script>

<style scoped>
.model-selector {
  width: 200px;
}
.option-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.model-provider {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
