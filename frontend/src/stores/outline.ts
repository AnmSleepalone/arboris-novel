import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  OutlineTreeResponse,
  PartWithVolumes,
  VolumeWithChapters,
  ChapterOutlineDetail,
  Part,
  Volume,
  PartCreate,
  PartUpdate,
  VolumeCreate,
  VolumeUpdate,
  GenerateResponse,
  PartsGenerationData,
  VolumesGenerationData,
  OutlineTreeNode,
  OutlineNodeType
} from '@/types/outline'
import { NovelAPI } from '@/api/novel'
import { useMessage } from 'naive-ui'

export const useOutlineStore = defineStore('outline', () => {
  // State
  const tree = ref<OutlineTreeResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const generating = ref(false)

  // Getters
  const hasTree = computed(() => tree.value !== null && tree.value.parts.length > 0)
  const totalParts = computed(() => tree.value?.parts.length || 0)
  const totalVolumes = computed(() => {
    if (!tree.value) return 0
    return tree.value.parts.reduce((sum, part) => sum + part.volumes.length, 0)
  })
  const totalChapters = computed(() => {
    if (!tree.value) return 0
    return tree.value.parts.reduce((sum, part) => {
      return sum + part.volumes.reduce((vSum, vol) => vSum + vol.chapters.length, 0)
    }, 0)
  })

  // 将树形数据转换为 Naive UI Tree 组件所需的格式
  const treeNodes = computed<OutlineTreeNode[]>(() => {
    if (!tree.value) return []

    return tree.value.parts.map((part) => ({
      key: `part-${part.id}`,
      label: part.title,
      type: 'part' as OutlineNodeType,
      data: part,
      children: part.volumes.map((volume) => ({
        key: `volume-${volume.id}`,
        label: volume.title,
        type: 'volume' as OutlineNodeType,
        data: volume,
        children: volume.chapters.map((chapter) => ({
          key: `chapter-${chapter.id}`,
          label: `第${chapter.chapter_number}章 ${chapter.title}`,
          type: 'chapter' as OutlineNodeType,
          data: chapter
        }))
      }))
    }))
  })

  // Actions

  /**
   * 加载完整树形大纲
   */
  async function loadTree(projectId: string) {
    loading.value = true
    error.value = null
    try {
      tree.value = await NovelAPI.getOutlineTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载大纲树失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ===================================================================
  // Part 操作
  // ===================================================================

  /**
   * 创建新的篇
   */
  async function createPart(projectId: string, data: PartCreate) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.createPart(projectId, data)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '创建篇失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 更新篇信息
   */
  async function updatePart(projectId: string, partId: number, data: PartUpdate) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.updatePart(projectId, partId, data)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '更新篇失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 删除篇
   */
  async function deletePart(projectId: string, partId: number) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.deletePart(projectId, partId)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '删除篇失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 重新排序篇
   */
  async function reorderParts(projectId: string, partIds: number[]) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.reorderParts(projectId, partIds)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '重排序篇失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ===================================================================
  // Volume 操作
  // ===================================================================

  /**
   * 创建新的卷
   */
  async function createVolume(projectId: string, partId: number, data: VolumeCreate) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.createVolume(projectId, partId, data)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '创建卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 更新卷信息
   */
  async function updateVolume(projectId: string, volumeId: number, data: VolumeUpdate) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.updateVolume(projectId, volumeId, data)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '更新卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 删除卷
   */
  async function deleteVolume(projectId: string, volumeId: number) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.deleteVolume(projectId, volumeId)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '删除卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 移动卷到其他篇
   */
  async function moveVolumeToPart(projectId: string, volumeId: number, targetPartId: number) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.moveVolumeTopart(projectId, volumeId, targetPartId)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '移动卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 重新排序卷
   */
  async function reorderVolumes(projectId: string, partId: number, volumeIds: number[]) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.reorderVolumes(projectId, partId, volumeIds)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '重排序卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ===================================================================
  // Chapter 操作
  // ===================================================================

  /**
   * 移动章节到其他卷
   */
  async function moveChapterToVolume(
    projectId: string,
    chapterOutlineId: number,
    targetVolumeId: number,
    newChapterNumber: number
  ) {
    loading.value = true
    error.value = null
    try {
      await NovelAPI.moveChapterToVolume(projectId, chapterOutlineId, targetVolumeId, newChapterNumber)
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '移动章节失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ===================================================================
  // LLM 生成
  // ===================================================================

  /**
   * 生成篇章结构
   */
  async function generateParts(projectId: string): Promise<PartsGenerationData> {
    generating.value = true
    error.value = null
    try {
      const response: GenerateResponse<PartsGenerationData> = await NovelAPI.generateParts(projectId)
      // 生成成功后不自动刷新树，等用户确认后再创建
      return response.data
    } catch (err) {
      error.value = err instanceof Error ? err.message : '生成篇章结构失败'
      throw err
    } finally {
      generating.value = false
    }
  }

  /**
   * 为指定篇生成卷结构
   */
  async function generateVolumes(projectId: string, partId: number): Promise<VolumesGenerationData> {
    generating.value = true
    error.value = null
    try {
      const response: GenerateResponse<VolumesGenerationData> = await NovelAPI.generateVolumes(projectId, partId)
      // 生成成功后不自动刷新树，等用户确认后再创建
      return response.data
    } catch (err) {
      error.value = err instanceof Error ? err.message : '生成卷结构失败'
      throw err
    } finally {
      generating.value = false
    }
  }

  /**
   * 批量创建篇（从生成结果）
   */
  async function batchCreatePartsFromGeneration(projectId: string, partsData: PartsGenerationData) {
    loading.value = true
    error.value = null
    try {
      for (const partData of partsData.parts) {
        await NovelAPI.createPart(projectId, {
          title: partData.title,
          description: partData.description
        })
      }
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '批量创建篇失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 批量创建卷（从生成结果）
   */
  async function batchCreateVolumesFromGeneration(
    projectId: string,
    partId: number,
    volumesData: VolumesGenerationData
  ) {
    loading.value = true
    error.value = null
    try {
      for (const volumeData of volumesData.volumes) {
        await NovelAPI.createVolume(projectId, partId, {
          title: volumeData.title,
          description: volumeData.description
        })
      }
      await loadTree(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '批量创建卷失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ===================================================================
  // 辅助方法
  // ===================================================================

  /**
   * 根据节点 key 查找节点数据
   */
  function findNodeByKey(key: string): { type: OutlineNodeType; data: any } | null {
    if (!tree.value) return null

    const [type, idStr] = key.split('-')
    const id = parseInt(idStr)

    if (type === 'part') {
      const part = tree.value.parts.find(p => p.id === id)
      return part ? { type: 'part', data: part } : null
    }

    for (const part of tree.value.parts) {
      if (type === 'volume') {
        const volume = part.volumes.find(v => v.id === id)
        if (volume) return { type: 'volume', data: volume }
      } else if (type === 'chapter') {
        for (const volume of part.volumes) {
          const chapter = volume.chapters.find(c => c.id === id)
          if (chapter) return { type: 'chapter', data: chapter }
        }
      }
    }

    return null
  }

  /**
   * 清空状态
   */
  function clearState() {
    tree.value = null
    error.value = null
    loading.value = false
    generating.value = false
  }

  return {
    // State
    tree,
    loading,
    error,
    generating,

    // Getters
    hasTree,
    totalParts,
    totalVolumes,
    totalChapters,
    treeNodes,

    // Part Actions
    createPart,
    updatePart,
    deletePart,
    reorderParts,

    // Volume Actions
    createVolume,
    updateVolume,
    deleteVolume,
    moveVolumeToPart,
    reorderVolumes,

    // Chapter Actions
    moveChapterToVolume,

    // LLM Generation
    generateParts,
    generateVolumes,
    batchCreatePartsFromGeneration,
    batchCreateVolumesFromGeneration,

    // Utility
    loadTree,
    findNodeByKey,
    clearState
  }
})
