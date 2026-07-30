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

    <el-empty v-if="!kbStore.knowledgeBases.length" description="暂无知识库" />
    <div v-else class="kb-grid">
      <div v-for="kb in kbStore.knowledgeBases" :key="kb.id" class="kb-card glass-card slide-up">
        <div class="kb-header">
          <h3>{{ kb.name }}</h3>
          <el-button v-if="authStore.isAdmin" type="danger" link @click="handleDelete(kb.id)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
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
          <el-button v-if="authStore.isAdmin" type="primary" plain size="small" @click="openUpload(kb)">
            上传并向量化
          </el-button>
          <el-button size="small" @click="openMilvusData(kb)">查看 Milvus 数据</el-button>
        </div>
      </div>
    </div>

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

    <el-dialog v-model="uploadVisible" title="上传文档并向量化" width="560px" @closed="resetUpload">
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
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="handleUpload">
          {{ uploading ? '处理中…' : '上传并处理' }}
        </el-button>
      </template>
    </el-dialog>

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
          <el-pagination
            v-if="chunkPage && chunkPage.total > pageSize"
            class="pagination"
            layout="prev, pager, next, total"
            :page-size="pageSize"
            :total="chunkPage.total"
            :current-page="currentPage"
            @current-change="handlePageChange"
          />
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
import type { KnowledgeBase, MilvusChunkPage, MilvusSchema } from '../types'

const kbStore = useKnowledgeStore()
const authStore = useAuthStore()
const dialogVisible = ref(false)
const uploadVisible = ref(false)
const dataVisible = ref(false)
const creating = ref(false)
const uploading = ref(false)
const dataLoading = ref(false)
const selectedFile = ref<File | null>(null)
const uploadTarget = ref<KnowledgeBase | null>(null)
const dataTarget = ref<KnowledgeBase | null>(null)
const schema = ref<MilvusSchema | null>(null)
const chunkPage = ref<MilvusChunkPage | null>(null)
const activeDataTab = ref('schema')
const currentPage = ref(1)
const pageSize = 20

const form = reactive({ name: '', description: '', vectorDimension: 1024 })
const uploadForm = reactive({ chunkTokens: 512, overlapTokens: 64 })
const acceptedExtensions = computed(() =>
  (kbStore.embeddingConfig?.supported_extensions || []).join(',')
)

const errorMessage = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || fallback
}

onMounted(async () => {
  try {
    await Promise.all([kbStore.fetchEmbeddingConfig(), kbStore.fetchKnowledgeBases()])
    form.vectorDimension = kbStore.embeddingConfig?.default_dimension || 1024
  } catch (error) {
    ElMessage.error(errorMessage(error, '知识库配置加载失败'))
  }
})

const handleCreate = async () => {
  if (!form.name.trim()) return ElMessage.warning('请输入名称')
  creating.value = true
  try {
    await kbStore.createKnowledgeBase(form.name.trim(), form.description, form.vectorDimension)
    dialogVisible.value = false
    form.name = ''
    form.description = ''
    ElMessage.success('知识库和 Milvus 集合创建成功')
  } catch (error) {
    ElMessage.error(errorMessage(error, '创建失败'))
  } finally {
    creating.value = false
  }
}

const handleDelete = async (id: number) => {
  try {
    await ElMessageBox.confirm('将同时删除 Milvus 集合及其中的全部向量，是否继续？', '删除知识库', {
      type: 'warning'
    })
    await kbStore.deleteKnowledgeBase(id)
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errorMessage(error, '删除失败'))
  }
}

const openUpload = (kb: KnowledgeBase) => {
  uploadTarget.value = kb
  uploadVisible.value = true
}

const handleFileChange = (uploadFile: UploadFile) => {
  selectedFile.value = uploadFile.raw || null
}

const handleFileRemove = () => {
  selectedFile.value = null
}

const resetUpload = () => {
  selectedFile.value = null
  uploadTarget.value = null
  uploadForm.chunkTokens = 512
  uploadForm.overlapTokens = 64
}

const handleUpload = async () => {
  if (!uploadTarget.value || !selectedFile.value) return ElMessage.warning('请选择文件')
  if (uploadForm.overlapTokens >= uploadForm.chunkTokens) {
    return ElMessage.warning('Overlap 必须小于切片 Token 数')
  }
  uploading.value = true
  try {
    const result = await kbStore.uploadDocument(
      uploadTarget.value.id,
      selectedFile.value,
      uploadForm.chunkTokens,
      uploadForm.overlapTokens
    )
    await kbStore.fetchKnowledgeBases()
    uploadVisible.value = false
    ElMessage.success(`处理完成：写入 ${result.chunk_count} 个切片`)
  } catch (error) {
    ElMessage.error(errorMessage(error, '上传或向量化失败'))
  } finally {
    uploading.value = false
  }
}

const loadMilvusData = async (page = 1) => {
  if (!dataTarget.value) return
  dataLoading.value = true
  try {
    const offset = (page - 1) * pageSize
    const [schemaResult, chunksResult] = await Promise.all([
      kbStore.fetchMilvusSchema(dataTarget.value.id),
      kbStore.fetchMilvusChunks(dataTarget.value.id, offset, pageSize)
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
  dataVisible.value = true
  await loadMilvusData(1)
}

const handlePageChange = async (page: number) => {
  await loadMilvusData(page)
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
.drawer-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.drawer-head h3 { margin: 0 0 6px; }
.drawer-head span { color: var(--text-secondary); font-size: 12px; }
.chunk-text { white-space: pre-wrap; max-height: 180px; overflow: auto; line-height: 1.55; font-size: 13px; }
.pagination { margin-top: 20px; justify-content: flex-end; }
</style>