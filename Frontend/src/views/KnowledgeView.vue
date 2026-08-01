<!-- 知识库列表卡片管理、文档异步上传向量化与 Milvus 切片深探探测视图组件 -->
<template>
  <div class="knowledge-container">
    <div class="header">
      <div>
        <h1 class="text-gradient">知识库管理</h1>
        <p class="subtitle">
          {{ kbStore.embeddingConfig?.provider || '向量服务' }} ·
          {{ kbStore.embeddingConfig?.model || '读取配置中' }}
        </p>
      </div>
      <el-button v-if="authStore.isAdmin" type="primary" @click="dialogVisible = true">
        <el-icon><Plus /></el-icon> 创建知识库
      </el-button>
    </div>

    <!-- 知识库卡片列表 -->
    <el-empty v-if="!kbStore.knowledgeBases.length" description="暂无知识库" />
    <div v-else class="kb-grid">
      <div v-for="kb in kbStore.knowledgeBases" :key="kb.id" class="kb-card glass-card slide-up">
        <div class="kb-header">
          <h3>{{ kb.name }}</h3>
          <el-button
            v-if="authStore.isAdmin && kb.status !== 'deleting'"
            type="danger"
            link
            @click="handleDelete(kb.id)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
        <el-tag :type="statusTagType(kb.status)" size="small">
          {{ statusText[kb.status] || kb.status }}
        </el-tag>
        <p class="kb-desc">{{ kb.description || '无描述' }}</p>
        <div class="model-line">
          <el-tag size="small" effect="plain">{{ kb.embedding_model }}</el-tag>
          <el-tag size="small" type="success" effect="plain">{{ kb.vector_dimension }} 维</el-tag>
        </div>
        <div class="kb-meta">
          <span><el-icon><Document /></el-icon> {{ kb.file_count }} 个文件</span>
          <span>{{ kb.chunk_count }} 个切片</span>
        </div>
        <div class="kb-actions">
          <el-button
            v-if="authStore.isAdmin"
            type="primary"
            plain
            size="small"
            :disabled="kb.status !== 'active'"
            @click="openUpload(kb)"
          >
            上传并向量化
          </el-button>
          <el-button
            size="small"
            :disabled="kb.status !== 'active'"
            @click="openMilvusData(kb)"
          >
            查看 Milvus 数据
          </el-button>
        </div>
      </div>
    </div>

    <!-- 创建知识库弹窗 -->
    <el-dialog v-model="dialogVisible" title="创建知识库" width="460px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" />
        </el-form-item>
        <el-form-item label="向量维度">
          <el-select v-model="form.vectorDimension" style="width: 100%">
            <el-option
              v-for="dimension in kbStore.embeddingConfig?.supported_dimensions || []"
              :key="dimension"
              :label="`${dimension} 维`"
              :value="dimension"
            />
          </el-select>
          <div class="form-tip">集合创建后维度不能修改，需要与向量模型输出一致。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>

    <!-- 上传文档并向量化弹窗 -->
    <el-dialog
      v-model="uploadVisible"
      title="上传文档并向量化"
      width="560px"
      :close-on-click-modal="!uploading"
      :show-close="!uploading"
      @closed="resetUpload"
    >
      <el-alert
        :title="`${uploadTarget?.name || ''} · ${uploadTarget?.vector_dimension || ''} 维`"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form class="upload-form" label-width="120px">
        <el-form-item label="选择文件">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :accept="acceptedExtensions"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入文件或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">
                支持 DOCX、Excel、PDF、TXT、Markdown、CSV，最大 30 MB。Excel 会先合并所有工作表。
              </div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item label="切片 Token 数">
          <el-input-number v-model="uploadForm.chunkTokens" :min="64" :max="8192" :step="64" />
        </el-form-item>
        <el-form-item label="Overlap Token 数">
          <el-input-number
            v-model="uploadForm.overlapTokens"
            :min="0"
            :max="Math.max(0, uploadForm.chunkTokens - 1)"
            :step="16"
          />
        </el-form-item>
        <div class="form-tip upload-tip">
          实际流程：提取/拼接全文 → token 切片 → {{ kbStore.embeddingConfig?.model }} → Milvus。
        </div>
        <div v-if="uploadTask" class="task-progress">
          <el-progress
            :percentage="uploadTask.progress"
            :status="uploadTask.status === 'failed' ? 'exception' : uploadTask.status === 'completed' ? 'success' : undefined"
          />
          <div class="task-stage">
            {{ taskStageText }}
            <span v-if="uploadTask.status === 'queued'">（任务已持久化，可安全等待）</span>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button :disabled="uploading" @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="handleUpload">
          {{ uploading ? taskStageText : '上传并处理' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Milvus 抽屉探针页面 -->
    <el-drawer v-model="dataVisible" size="75%" title="Milvus 数据查看">
      <div v-if="dataTarget" class="drawer-head">
        <div>
          <h3>{{ dataTarget.name }}</h3>
          <span>{{ schema?.collection_name }}</span>
        </div>
        <el-tag>{{ schema?.entity_count || 0 }} 条向量</el-tag>
      </div>

      <el-tabs v-model="activeDataTab" v-loading="dataLoading">
        <el-tab-pane label="数据字段" name="schema">
          <el-table :data="schema?.fields || []" stripe>
            <el-table-column prop="name" label="字段" min-width="150" />
            <el-table-column prop="type" label="类型" width="150" />
            <el-table-column label="主键" width="90">
              <template #default="scope">{{ scope.row.is_primary ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column prop="dimension" label="维度" width="100" />
            <el-table-column prop="max_length" label="最大长度" width="120" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="处理后切片" name="chunks">
          <el-table :data="chunkPage?.items || []" stripe row-key="id">
            <el-table-column prop="id" label="ID" width="90" />
            <el-table-column prop="document_name" label="文件" min-width="160" show-overflow-tooltip />
            <el-table-column prop="chunk_index" label="切片" width="80" />
            <el-table-column prop="token_count" label="Token" width="90" />
            <el-table-column label="切片内容" min-width="420">
              <template #default="scope">
                <div class="chunk-text">{{ scope.row.text }}</div>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="chunkPage && chunkPage.total > pageSize" class="cursor-pagination">
            <span>第 {{ currentPage }} 页 · 共 {{ chunkPage.total }} 条</span>
            <div>
              <el-button :disabled="currentPage <= 1" @click="handlePreviousPage">上一页</el-button>
              <el-button :disabled="chunkPage.next_cursor === null" @click="handleNextPage">下一页</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Delete, Document, Plus, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { useKnowledgeStore } from '../stores/knowledge'
import { useAuthStore } from '../stores/auth'
import type { DocumentTask, KnowledgeBase, MilvusChunkPage, MilvusSchema } from '../types'

const kbStore = useKnowledgeStore()
const authStore = useAuthStore()
const dialogVisible = ref(false)
const uploadVisible = ref(false)
const dataVisible = ref(false)
const creating = ref(false)
const uploading = ref(false)
const dataLoading = ref(false)
const selectedFile = ref<File | null>(null)
const uploadTask = ref<DocumentTask | null>(null)
const uploadTarget = ref<KnowledgeBase | null>(null)
const dataTarget = ref<KnowledgeBase | null>(null)
const schema = ref<MilvusSchema | null>(null)
const chunkPage = ref<MilvusChunkPage | null>(null)
const activeDataTab = ref('schema')
const currentPage = ref(1)
const pageSize = 20
const cursorHistory = ref<(number | null)[]>([null])

const form = reactive({ name: '', description: '', vectorDimension: 1024 })
const uploadForm = reactive({ chunkTokens: 512, overlapTokens: 64 })
const acceptedExtensions = computed(() =>
  (kbStore.embeddingConfig?.supported_extensions || []).join(',')
)

const stageNames: Record<string, string> = {
  queued: '等待处理',
  parsing: '正在解析文档',
  splitting: '正在切分文本',
  embedding: '正在生成向量',
  milvus: '正在写入 Milvus',
  metadata: '正在保存元信息',
  completed: '处理完成',
  failed: '处理失败'
}
const statusText: Record<string, string> = {
  creating: '创建中',
  active: '可用',
  deleting: '删除中',
  create_failed: '创建失败',
  delete_failed: '删除失败',
  inconsistent: '数据不一致'
}

const statusTagType = (status: string) => {
  if (status === 'active') return 'success'
  if (status.endsWith('failed')) return 'danger'
  return 'warning'
}

const taskStageText = computed(() =>
  stageNames[uploadTask.value?.stage || 'queued'] || '处理中'
)

const errorMessage = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || (error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    await Promise.all([kbStore.fetchEmbeddingConfig(), kbStore.fetchKnowledgeBases()])
    form.vectorDimension = kbStore.embeddingConfig?.default_dimension || 1024
  } catch (error) {
    ElMessage.error(errorMessage(error, '知识库配置加载失败'))
  }
})

/** 创建知识库提交句柄 */
const handleCreate = async () => {
  if (!form.name.trim()) return ElMessage.warning('请输入名称')
  creating.value = true
  try {
    const completed = await kbStore.createKnowledgeBase(
      form.name.trim(),
      form.description,
      form.vectorDimension
    )
    dialogVisible.value = false
    form.name = ''
    form.description = ''
    if (completed) {
      ElMessage.success('知识库和 Milvus 集合创建成功')
    } else {
      ElMessage.info('创建任务仍在后台重试，可通过状态标签查看进度')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, '创建失败'))
  } finally {
    creating.value = false
  }
}

/** 删除知识库提交句柄 */
const handleDelete = async (id: number) => {
  try {
    await ElMessageBox.confirm('将同时删除 Milvus 集合及其中的全部向量，是否继续？', '删除知识库', {
      type: 'warning'
    })
    const completed = await kbStore.deleteKnowledgeBase(id)
    if (completed) {
      ElMessage.success('Milvus 与 MySQL 记录均已删除')
    } else {
      ElMessage.info('删除任务仍在后台重试，知识库已停止使用')
    }
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errorMessage(error, '删除失败'))
  }
}

/** 打开上传弹窗 */
const openUpload = (kb: KnowledgeBase) => {
  uploadTarget.value = kb
  uploadVisible.value = true
}

const handleFileChange = (uploadFile: UploadFile) => {
  selectedFile.value = uploadFile.raw || null
}

const handleFileRemove = () => {
  selectedFile.value = null
  uploadTask.value = null
}

const resetUpload = () => {
  selectedFile.value = null
  uploadTarget.value = null
  uploadForm.chunkTokens = 512
  uploadForm.overlapTokens = 64
}

/** 上传文档并轮询异步生成进度 */
const handleUpload = async () => {
  if (!uploadTarget.value || !selectedFile.value) return ElMessage.warning('请选择文件')
  if (uploadForm.overlapTokens >= uploadForm.chunkTokens) {
    return ElMessage.warning('Overlap 必须小于切片 Token 数')
  }
  uploading.value = true
  try {
    uploadTask.value = await kbStore.uploadDocument(
      uploadTarget.value.id,
      selectedFile.value,
      uploadForm.chunkTokens,
      uploadForm.overlapTokens
    )
    while (
      uploadTask.value.status === 'queued' ||
      uploadTask.value.status === 'processing'
    ) {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      uploadTask.value = await kbStore.fetchDocumentTask(uploadTask.value.id)
    }
    if (uploadTask.value.status === 'failed') {
      throw new Error(uploadTask.value.error || '文档处理失败')
    }
    await kbStore.fetchKnowledgeBases()
    ElMessage.success('文档解析、向量化和入库完成')
    await new Promise(resolve => window.setTimeout(resolve, 500))
    uploadVisible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error, '上传或向量化失败'))
  } finally {
    uploading.value = false
  }
}

/** 读取 Milvus 底层 Schema 与向量切片 */
const loadMilvusData = async (cursor: number | null = null, page = 1) => {
  if (!dataTarget.value) return
  dataLoading.value = true
  try {
    const [schemaResult, chunksResult] = await Promise.all([
      kbStore.fetchMilvusSchema(dataTarget.value.id),
      kbStore.fetchMilvusChunks(dataTarget.value.id, 0, pageSize, cursor)
    ])
    schema.value = schemaResult
    chunkPage.value = chunksResult
    currentPage.value = page
  } catch (error) {
    ElMessage.error(errorMessage(error, '读取 Milvus 数据失败'))
  } finally {
    dataLoading.value = false
  }
}

const openMilvusData = async (kb: KnowledgeBase) => {
  dataTarget.value = kb
  activeDataTab.value = 'schema'
  cursorHistory.value = [null]
  dataVisible.value = true
  await loadMilvusData(null, 1)
}

const handleNextPage = async () => {
  if (chunkPage.value?.next_cursor === null || chunkPage.value?.next_cursor === undefined) return
  cursorHistory.value.push(chunkPage.value.next_cursor)
  await loadMilvusData(chunkPage.value.next_cursor, cursorHistory.value.length)
}

const handlePreviousPage = async () => {
  if (cursorHistory.value.length <= 1) return
  cursorHistory.value.pop()
  await loadMilvusData(
    cursorHistory.value[cursorHistory.value.length - 1],
    cursorHistory.value.length
  )
}
</script>

<style scoped>
.knowledge-container { padding: 40px; height: 100%; overflow-y: auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
.header h1 { font-size: 24px; margin: 0; }
.subtitle { margin: 8px 0 0; color: var(--text-secondary); font-size: 13px; }
.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 24px; }
.kb-card { padding: 24px; display: flex; flex-direction: column; transition: transform .3s ease, box-shadow .3s ease; }
.kb-card:hover { transform: translateY(-4px); box-shadow: var(--shadow-lg); border-color: var(--color-primary); }
.kb-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.kb-header h3 { margin: 0; font-size: 18px; color: var(--text-primary); }
.kb-desc { color: var(--text-secondary); font-size: 14px; min-height: 42px; }
.model-line { display: flex; gap: 8px; margin: 8px 0 18px; }
.kb-meta { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; }
.kb-meta span { display: flex; align-items: center; gap: 4px; }
.kb-actions { border-top: 1px solid var(--border-color); padding-top: 16px; display: flex; gap: 8px; }
.form-tip { color: var(--text-secondary); font-size: 12px; line-height: 1.5; margin-top: 6px; }
.upload-form { margin-top: 22px; }
.upload-form :deep(.el-upload), .upload-form :deep(.el-upload-dragger) { width: 100%; }
.upload-tip { margin-left: 120px; }
.task-progress { margin: 22px 0 0 120px; }
.task-stage { margin-top: 8px; color: var(--text-secondary); font-size: 12px; }
.drawer-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.drawer-head h3 { margin: 0 0 6px; }
.drawer-head span { color: var(--text-secondary); font-size: 12px; }
.chunk-text { white-space: pre-wrap; max-height: 180px; overflow: auto; line-height: 1.55; font-size: 13px; }
.cursor-pagination { margin-top: 20px; display: flex; align-items: center; justify-content: space-between; color: var(--text-secondary); font-size: 13px; }
</style>
