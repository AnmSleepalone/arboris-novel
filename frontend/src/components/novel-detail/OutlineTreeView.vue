<template>
  <div class="outline-tree-view">
    <!-- 工具栏 -->
    <div class="tree-toolbar">
      <n-space>
        <n-button
          type="primary"
          size="small"
          @click="handleGenerateParts"
          :loading="outlineStore.generating"
        >
          <template #icon>
            <n-icon>
              <SparklesOutline />
            </n-icon>
          </template>
          AI 生成篇章结构
        </n-button>
        <n-button size="small" @click="handleCreatePart">
          <template #icon>
            <n-icon>
              <AddOutline />
            </n-icon>
          </template>
          手动添加篇
        </n-button>
        <n-button size="small" @click="handleRefresh" :loading="outlineStore.loading">
          <template #icon>
            <n-icon>
              <RefreshOutline />
            </n-icon>
          </template>
          刷新
        </n-button>
      </n-space>

      <!-- 统计信息 -->
      <n-space v-if="outlineStore.hasTree" class="tree-stats">
        <n-tag size="small" type="info"> {{ outlineStore.totalParts }} 篇 </n-tag>
        <n-tag size="small" type="success"> {{ outlineStore.totalVolumes }} 卷 </n-tag>
        <n-tag size="small" type="warning"> {{ outlineStore.totalChapters }} 章 </n-tag>
      </n-space>
    </div>

    <!-- 树形结构 -->
    <div class="tree-container" v-if="outlineStore.hasTree">
      <n-tree
        :data="outlineStore.treeNodes"
        :block-line="true"
        :show-irrelevant-nodes="false"
        :render-label="renderLabel"
        :render-suffix="renderSuffix"
        :default-expanded-keys="defaultExpandedKeys"
        key-field="key"
        label-field="label"
        children-field="children"
      />
    </div>

    <!-- 空状态 -->
    <n-empty
      v-else-if="!outlineStore.loading"
      description="还没有大纲结构，点击上方按钮开始创建"
      class="empty-state"
    >
      <template #icon>
        <n-icon size="48" :component="DocumentTextOutline" />
      </template>
    </n-empty>

    <!-- Part 编辑/创建模态框 -->
    <n-modal
      v-model:show="partModalVisible"
      preset="dialog"
      :title="partModalMode === 'create' ? '创建篇' : '编辑篇'"
      positive-text="确定"
      negative-text="取消"
      @positive-click="handlePartModalConfirm"
    >
      <n-form ref="partFormRef" :model="partFormData" :rules="partFormRules" label-placement="top">
        <n-form-item label="篇标题" path="title">
          <n-input v-model:value="partFormData.title" placeholder="请输入篇标题，如：道途险" />
        </n-form-item>
        <n-form-item label="描述" path="description">
          <n-input
            v-model:value="partFormData.description"
            type="textarea"
            :rows="4"
            placeholder="请输入该篇的核心内容描述，包括主要场景、核心冲突等"
          />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- Volume 编辑/创建模态框 -->
    <n-modal
      v-model:show="volumeModalVisible"
      preset="dialog"
      :title="volumeModalMode === 'create' ? '创建卷' : '编辑卷'"
      positive-text="确定"
      negative-text="取消"
      @positive-click="handleVolumeModalConfirm"
    >
      <n-form
        ref="volumeFormRef"
        :model="volumeFormData"
        :rules="volumeFormRules"
        label-placement="top"
      >
        <n-form-item label="卷标题" path="title">
          <n-input v-model:value="volumeFormData.title" placeholder="请输入卷标题，如：入宗考验" />
        </n-form-item>
        <n-form-item label="描述" path="description">
          <n-input
            v-model:value="volumeFormData.description"
            type="textarea"
            :rows="4"
            placeholder="请输入该卷的核心事件、冲突、转折点"
          />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- AI 生成结果预览模态框 -->
    <n-modal
      v-model:show="generationPreviewVisible"
      preset="card"
      :title="generationPreviewTitle"
      style="width: 800px"
      :segmented="true"
    >
      <n-scrollbar style="max-height: 500px">
        <div v-if="generatedPartsData">
          <n-alert type="info" style="margin-bottom: 16px">
            {{ generatedPartsData.rationale }}
          </n-alert>
          <n-list bordered>
            <n-list-item v-for="part in generatedPartsData.parts" :key="part.part_number">
              <template #prefix>
                <n-tag type="primary">第{{ part.part_number }}篇</n-tag>
              </template>
              <n-thing :title="part.title">
                <template #description>
                  <n-text depth="3">{{ part.theme }}</n-text>
                </template>
                <n-text>{{ part.description }}</n-text>
                <template #footer>
                  <n-tag size="small" type="success"> 预计 {{ part.estimated_chapters }} 章 </n-tag>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>
        </div>

        <div v-if="generatedVolumesData">
          <n-alert type="info" style="margin-bottom: 16px">
            {{ generatedVolumesData.rationale }}
          </n-alert>
          <n-list bordered>
            <n-list-item v-for="volume in generatedVolumesData.volumes" :key="volume.volume_number">
              <template #prefix>
                <n-tag type="success">第{{ volume.volume_number }}卷</n-tag>
              </template>
              <n-thing :title="volume.title">
                <template #description>
                  <n-text depth="3">{{ volume.conflict }}</n-text>
                </template>
                <n-text>{{ volume.description }}</n-text>
                <template #footer>
                  <n-tag size="small" type="warning">
                    预计 {{ volume.estimated_chapters }} 章
                  </n-tag>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>
        </div>
      </n-scrollbar>

      <template #footer>
        <n-space justify="end">
          <n-button @click="generationPreviewVisible = false">取消</n-button>
          <n-button type="primary" @click="handleConfirmGeneration" :loading="outlineStore.loading">
            确认并创建
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Chapter 编辑/创建模态框 -->
    <n-modal
      v-model:show="chapterModalVisible"
      preset="dialog"
      :title="chapterModalMode === 'create' ? '创建章节' : '编辑章节'"
      positive-text="确定"
      negative-text="取消"
      @positive-click="handleChapterModalConfirm"
    >
      <n-form
        ref="chapterFormRef"
        :model="chapterFormData"
        :rules="chapterFormRules"
        label-placement="top"
      >
        <n-form-item label="章节标题" path="title">
          <n-input
            v-model:value="chapterFormData.title"
            placeholder="请输入章节标题,如:初入剑宗"
          />
        </n-form-item>
        <n-form-item label="摘要" path="summary">
          <n-input
            v-model:value="chapterFormData.summary"
            type="textarea"
            :rows="4"
            placeholder="请输入本章的主要内容摘要"
          />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- 移动章节模态框 -->
    <n-modal
      v-model:show="moveChapterModalVisible"
      preset="dialog"
      title="移动章节"
      positive-text="确定"
      negative-text="取消"
      @positive-click="handleConfirmMoveChapter"
    >
      <div style="margin-bottom: 16px">
        <n-text strong>将章节《{{ moveChapterData?.title }}》移动到:</n-text>
      </div>

      <n-space vertical :size="16">
        <div>
          <n-text depth="3" style="margin-bottom: 8px; display: block">目标卷</n-text>
          <n-select
            v-model:value="targetVolumeId"
            :options="availableVolumes.map(v => ({
              label: `${v.partTitle} - ${v.label}`,
              value: v.value
            }))"
            placeholder="请选择目标卷"
          />
        </div>

        <div v-if="targetVolumeId">
          <n-text depth="3" style="margin-bottom: 8px; display: block">插入位置</n-text>
          <n-select
            v-model:value="targetPosition"
            :options="positionOptions"
            placeholder="请选择插入位置"
          />
        </div>
      </n-space>

      <n-alert
        v-if="targetVolumeId === moveChapterData?.volume_id"
        type="info"
        style="margin-top: 16px"
        :bordered="false"
      >
        在当前卷内调整章节顺序
      </n-alert>
      <n-alert
        v-else-if="targetVolumeId"
        type="warning"
        style="margin-top: 16px"
        :bordered="false"
      >
        章节将从当前卷移动到选中的卷
      </n-alert>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NTree,
  NButton,
  NIcon,
  NSpace,
  NTag,
  NEmpty,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NDropdown,
  NText,
  NAlert,
  NList,
  NListItem,
  NThing,
  NScrollbar,
  useMessage,
  useDialog,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import {
  AddOutline,
  SparklesOutline,
  RefreshOutline,
  CreateOutline,
  TrashOutline,
  DocumentTextOutline,
  EllipsisVerticalOutline,
} from '@vicons/ionicons5'
import { useOutlineStore } from '@/stores/outline'
import type {
  OutlineTreeNode,
  Part,
  Volume,
  ChapterOutlineDetail,
  PartsGenerationData,
  VolumesGenerationData,
} from '@/types/outline'
import { NovelAPI } from '@/api/novel'

const route = useRoute()
const message = useMessage()
const dialog = useDialog()
const outlineStore = useOutlineStore()

const projectId = computed(() => route.params.id as string)

// 默认展开的节点
const defaultExpandedKeys = ref<string[]>([])

// Part 模态框状态
const partModalVisible = ref(false)
const partModalMode = ref<'create' | 'edit'>('create')
const partFormRef = ref<FormInst | null>(null)
const partFormData = ref({
  id: 0,
  title: '',
  description: '',
})
const partFormRules: FormRules = {
  title: [{ required: true, message: '请输入篇标题', trigger: 'blur' }],
}

// Volume 模态框状态
const volumeModalVisible = ref(false)
const volumeModalMode = ref<'create' | 'edit'>('create')
const currentPartId = ref<number>(0)
const volumeFormRef = ref<FormInst | null>(null)
const volumeFormData = ref({
  id: 0,
  title: '',
  description: '',
})
const volumeFormRules: FormRules = {
  title: [{ required: true, message: '请输入卷标题', trigger: 'blur' }],
}

// AI 生成预览
const generationPreviewVisible = ref(false)
const generationPreviewTitle = ref('')
const generatedPartsData = ref<PartsGenerationData | null>(null)
const generatedVolumesData = ref<VolumesGenerationData | null>(null)

// Chapter 模态框状态
const chapterModalVisible = ref(false)
const chapterModalMode = ref<'create' | 'edit'>('create')
const currentVolumeId = ref<number>(0)
const chapterFormRef = ref<FormInst | null>(null)
const chapterFormData = ref({
  id: 0,
  title: '',
  summary: ''
})
const chapterFormRules: FormRules = {
  title: [
    { required: true, message: '请输入章节标题', trigger: 'blur' }
  ]
}

// 移动章节模态框状态
const moveChapterModalVisible = ref(false)
const moveChapterData = ref<ChapterOutlineDetail | null>(null)
const targetVolumeId = ref<number | null>(null)
const targetPosition = ref<number>(1) // 目标位置(章节号)

// 获取所有可选的卷列表(包括当前卷,支持同卷移动)
const availableVolumes = computed(() => {
  if (!outlineStore.tree) return []
  const volumes: Array<{ value: number; label: string; partTitle: string }> = []
  outlineStore.tree.parts.forEach(part => {
    part.volumes.forEach(volume => {
      volumes.push({
        value: volume.id,
        label: `${volume.title}`,
        partTitle: part.title
      })
    })
  })
  return volumes
})

// 获取目标卷的章节列表,用于选择插入位置
const targetVolumeChapters = computed(() => {
  if (!targetVolumeId.value || !outlineStore.tree) return []

  const targetVolume = outlineStore.tree.parts
    .flatMap(p => p.volumes)
    .find(v => v.id === targetVolumeId.value)

  if (!targetVolume) return []

  // 过滤掉当前要移动的章节
  const chapters = targetVolume.chapters.filter(
    ch => ch.id !== moveChapterData.value?.id
  )

  return chapters
})

// 生成位置选项
const positionOptions = computed(() => {
  const options: Array<{ label: string; value: number }> = []
  const count = targetVolumeChapters.value.length

  // 如果目标卷是当前卷,章节数要减1(因为要移走一个章节)
  const isSameVolume = targetVolumeId.value === moveChapterData.value?.volume_id
  const totalPositions = isSameVolume ? count + 1 : count + 1

  for (let i = 1; i <= totalPositions; i++) {
    if (i === totalPositions) {
      options.push({ label: `末尾 (第 ${i} 章)`, value: i })
    } else {
      const existingChapter = targetVolumeChapters.value[i - 1]
      options.push({
        label: `第 ${i} 章 (在《${existingChapter?.title}》之前)`,
        value: i
      })
    }
  }

  return options
})

// 初始化
onMounted(async () => {
  await loadTree()
})

// 监听目标卷变化,自动重置位置为末尾
watch(targetVolumeId, () => {
  if (targetVolumeId.value && positionOptions.value.length > 0) {
    targetPosition.value = positionOptions.value[positionOptions.value.length - 1].value
  }
})

async function loadTree() {
  try {
    await outlineStore.loadTree(projectId.value)
    // 默认展开第一层
    if (outlineStore.tree) {
      defaultExpandedKeys.value = outlineStore.tree.parts.map((p) => `part-${p.id}`)
    }
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载失败')
  }
}

// ===================================================================
// 树节点渲染
// ===================================================================

function renderLabel({ option }: { option: OutlineTreeNode }) {
  const node = option as OutlineTreeNode

  if (node.type === 'part') {
    const part = node.data as Part
    return h('div', { class: 'tree-node-part' }, [
      h('span', { class: 'node-label' }, part.title),
      part.description &&
        h('span', { class: 'node-desc' }, ` - ${part.description.substring(0, 30)}...`),
    ])
  }

  if (node.type === 'volume') {
    const volume = node.data as Volume
    return h('div', { class: 'tree-node-volume' }, [
      h('span', { class: 'node-label' }, volume.title),
      volume.description &&
        h('span', { class: 'node-desc' }, ` - ${volume.description.substring(0, 30)}...`),
    ])
  }

  // chapter
  return h('div', { class: 'tree-node-chapter' }, node.label)
}

function renderSuffix({ option }: { option: OutlineTreeNode }) {
  const node = option as OutlineTreeNode

  const actions: any[] = []

  if (node.type === 'part') {
    const part = node.data as Part
    actions.push(
      { label: '编辑', key: 'edit-part', props: { onClick: () => handleEditPart(part) } },
      {
        label: 'AI 生成卷',
        key: 'generate-volumes',
        props: { onClick: () => handleGenerateVolumes(part) },
      },
      {
        label: '手动添加卷',
        key: 'add-volume',
        props: { onClick: () => handleCreateVolume(part.id) },
      },
      { type: 'divider' },
      { label: '删除', key: 'delete-part', props: { onClick: () => handleDeletePart(part) } },
    )
  }

  if (node.type === 'volume') {
    const volume = node.data as Volume
    actions.push(
      { label: '编辑', key: 'edit-volume', props: { onClick: () => handleEditVolume(volume) } },
      { label: '添加章节', key: 'add-chapter', props: { onClick: () => handleAddChapter(volume) } },
      { type: 'divider' },
      { label: '删除', key: 'delete-volume', props: { onClick: () => handleDeleteVolume(volume) } },
    )
  }

  if (node.type === 'chapter') {
    const chapter = node.data as ChapterOutlineDetail
    actions.push(
      { label: '编辑章节', key: 'edit-chapter', props: { onClick: () => handleEditChapter(chapter) } },
      { label: '移动到其他卷', key: 'move-chapter', props: { onClick: () => handleMoveChapter(chapter) } },
      { type: 'divider' },
      { label: '删除', key: 'delete-chapter', props: { onClick: () => handleDeleteChapter(chapter) } }
    )
  }

  return h(
    NDropdown,
    {
      trigger: 'hover',
      options: actions,
      placement: 'bottom-start',
    },
    {
      default: () =>
        h(
          NButton,
          {
            text: true,
            size: 'small',
            class: 'tree-node-action',
          },
          {
            icon: () => h(NIcon, { component: EllipsisVerticalOutline }),
          },
        ),
    },
  )
}

// ===================================================================
// Part 操作
// ===================================================================

function handleCreatePart() {
  partModalMode.value = 'create'
  partFormData.value = {
    id: 0,
    title: '',
    description: '',
  }
  partModalVisible.value = true
}

function handleEditPart(part: Part) {
  partModalMode.value = 'edit'
  partFormData.value = {
    id: part.id,
    title: part.title,
    description: part.description || '',
  }
  partModalVisible.value = true
}

async function handlePartModalConfirm() {
  await partFormRef.value?.validate()

  try {
    if (partModalMode.value === 'create') {
      await outlineStore.createPart(projectId.value, {
        title: partFormData.value.title,
        description: partFormData.value.description,
      })
      message.success('创建成功')
    } else {
      await outlineStore.updatePart(projectId.value, partFormData.value.id, {
        title: partFormData.value.title,
        description: partFormData.value.description,
      })
      message.success('更新成功')
    }
    partModalVisible.value = false
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
    return false
  }
}

function handleDeletePart(part: Part) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除篇《${part.title}》吗？这将同时删除其下所有卷和章节！`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await outlineStore.deletePart(projectId.value, part.id)
        message.success('删除成功')
      } catch (err) {
        message.error(err instanceof Error ? err.message : '删除失败')
      }
    },
  })
}

// ===================================================================
// Volume 操作
// ===================================================================

function handleCreateVolume(partId: number) {
  volumeModalMode.value = 'create'
  currentPartId.value = partId
  volumeFormData.value = {
    id: 0,
    title: '',
    description: '',
  }
  volumeModalVisible.value = true
}

function handleEditVolume(volume: Volume) {
  volumeModalMode.value = 'edit'
  volumeFormData.value = {
    id: volume.id,
    title: volume.title,
    description: volume.description || '',
  }
  volumeModalVisible.value = true
}

async function handleVolumeModalConfirm() {
  await volumeFormRef.value?.validate()

  try {
    if (volumeModalMode.value === 'create') {
      await outlineStore.createVolume(projectId.value, currentPartId.value, {
        title: volumeFormData.value.title,
        description: volumeFormData.value.description,
      })
      message.success('创建成功')
    } else {
      await outlineStore.updateVolume(projectId.value, volumeFormData.value.id, {
        title: volumeFormData.value.title,
        description: volumeFormData.value.description,
      })
      message.success('更新成功')
    }
    volumeModalVisible.value = false
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
    return false
  }
}

function handleDeleteVolume(volume: Volume) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除卷《${volume.title}》吗？这将同时删除其下所有章节！`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await outlineStore.deleteVolume(projectId.value, volume.id)
        message.success('删除成功')
      } catch (err) {
        message.error(err instanceof Error ? err.message : '删除失败')
      }
    },
  })
}

// ===================================================================
// AI 生成
// ===================================================================

async function handleGenerateParts() {
  try {
    const result = await outlineStore.generateParts(projectId.value)
    generatedPartsData.value = result
    generatedVolumesData.value = null
    generationPreviewTitle.value = 'AI 生成篇章结构'
    generationPreviewVisible.value = true
  } catch (err) {
    message.error(err instanceof Error ? err.message : '生成失败')
  }
}

async function handleGenerateVolumes(part: Part) {
  try {
    const result = await outlineStore.generateVolumes(projectId.value, part.id)
    generatedVolumesData.value = result
    generatedPartsData.value = null
    currentPartId.value = part.id
    generationPreviewTitle.value = `为《${part.title}》生成卷结构`
    generationPreviewVisible.value = true
  } catch (err) {
    message.error(err instanceof Error ? err.message : '生成失败')
  }
}

async function handleConfirmGeneration() {
  try {
    if (generatedPartsData.value) {
      await outlineStore.batchCreatePartsFromGeneration(projectId.value, generatedPartsData.value)
      message.success('已创建所有篇')
    } else if (generatedVolumesData.value) {
      await outlineStore.batchCreateVolumesFromGeneration(
        projectId.value,
        currentPartId.value,
        generatedVolumesData.value,
      )
      message.success('已创建所有卷')
    }
    generationPreviewVisible.value = false
  } catch (err) {
    message.error(err instanceof Error ? err.message : '创建失败')
  }
}

// ===================================================================
// Chapter 操作
// ===================================================================

function handleAddChapter(volume: Volume) {
  chapterModalMode.value = 'create'
  currentVolumeId.value = volume.id
  chapterFormData.value = {
    id: 0,
    title: '',
    summary: ''
  }
  chapterModalVisible.value = true
}

function handleEditChapter(chapter: ChapterOutlineDetail) {
  chapterModalMode.value = 'edit'
  chapterFormData.value = {
    id: chapter.id,
    title: chapter.title,
    summary: chapter.summary || ''
  }
  chapterModalVisible.value = true
}

async function handleChapterModalConfirm() {
  await chapterFormRef.value?.validate()

  try {
    if (chapterModalMode.value === 'create') {
      await NovelAPI.createChapterOutline(projectId.value, currentVolumeId.value, {
        title: chapterFormData.value.title,
        summary: chapterFormData.value.summary
      })
      message.success('创建成功')
    } else {
      await NovelAPI.updateChapterOutline(projectId.value, chapterFormData.value.id, {
        title: chapterFormData.value.title,
        summary: chapterFormData.value.summary
      })
      message.success('更新成功')
    }
    chapterModalVisible.value = false
    await loadTree()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
    return false
  }
}

function handleDeleteChapter(chapter: ChapterOutlineDetail) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除章节《${chapter.title}》吗？`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await NovelAPI.deleteChapterOutline(projectId.value, chapter.id)
        message.success('删除成功')
        await loadTree()
      } catch (err) {
        message.error(err instanceof Error ? err.message : '删除失败')
      }
    }
  })
}

function handleMoveChapter(chapter: ChapterOutlineDetail) {
  moveChapterData.value = chapter
  // 默认选择当前卷
  targetVolumeId.value = chapter.volume_id
  // 默认位置设为末尾
  targetPosition.value = 1
  moveChapterModalVisible.value = true
}

async function handleConfirmMoveChapter() {
  if (!moveChapterData.value || !targetVolumeId.value || !targetPosition.value) {
    message.error('请选择目标卷和位置')
    return false
  }

  try {
    await NovelAPI.moveChapterToVolume(
      projectId.value,
      moveChapterData.value.id,
      targetVolumeId.value,
      targetPosition.value
    )
    message.success('移动成功')
    moveChapterModalVisible.value = false
    await loadTree()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '移动失败')
    return false
  }
}

// ===================================================================
// 其他操作
// ===================================================================

function handleRefresh() {
  loadTree()
}
</script>

<style scoped>
.outline-tree-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.tree-toolbar {
  padding: 16px;
  border-bottom: 1px solid var(--n-border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tree-stats {
  display: flex;
  gap: 8px;
}

.tree-container {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.empty-state {
  padding: 64px 0;
}

.tree-node-part,
.tree-node-volume,
.tree-node-chapter {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-label {
  font-weight: 500;
}

.node-desc {
  font-size: 12px;
  color: var(--n-text-color-disabled);
}

.tree-node-action {
  opacity: 0;
  transition: opacity 0.2s;
}

:deep(.n-tree-node:hover) .tree-node-action {
  opacity: 1;
}
</style>
