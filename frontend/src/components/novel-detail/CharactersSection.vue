<template>
  <div class="space-y-6">
    <!-- 标题栏和操作区 -->
    <div class="flex items-center justify-between flex-wrap gap-4">
      <div>
        <h2 class="text-2xl font-bold text-slate-900">主要角色</h2>
        <p class="text-sm text-slate-500">了解故事中核心人物的目标与个性</p>
      </div>
      <div class="flex items-center gap-3">
        <!-- 分组筛选 -->
        <n-select
          v-model:value="selectedGroup"
          placeholder="筛选分组"
          clearable
          :options="groupFilterOptions"
          class="w-40" />

        <!-- 管理分组按钮 -->
        <n-button
          @click="showGroupManage = true">
          管理分组
        </n-button>

        <!-- 原有编辑按钮 -->
        <button
          v-if="editable"
          type="button"
          class="text-gray-400 hover:text-indigo-600 transition-colors"
          @click="emitEdit('characters', '主要角色', data?.characters)">
          <svg class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor">
            <path d="M17.414 2.586a2 2 0 00-2.828 0L7 10.172V13h2.828l7.586-7.586a2 2 0 000-2.828z" />
            <path fill-rule="evenodd" d="M2 6a2 2 0 012-2h4a1 1 0 010 2H4v10h10v-4a1 1 0 112 0v4a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 角色卡片网格 -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <article
        v-for="character in filteredCharacters"
        :key="character.id"
        class="bg-white/95 rounded-2xl border border-slate-200 shadow-sm hover:shadow-lg transition-all duration-300">
        <div class="p-6">
          <!-- 角色头部:图片+基本信息 -->
          <div class="flex flex-col sm:flex-row sm:items-start gap-4 mb-4">
            <!-- 角色图片 -->
            <div class="relative shrink-0">
              <div
                v-if="character.image_path"
                class="w-20 h-20 rounded-full overflow-hidden border-2 border-indigo-100">
                <img
                  :src="getImageUrl(character.image_path)"
                  :alt="character.name"
                  class="w-full h-full object-cover"
                  @error="handleImageError" />
              </div>
              <div
                v-else
                class="w-20 h-20 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 text-2xl font-semibold">
                {{ character.name?.slice(0, 1) || '角' }}
              </div>
            </div>

            <!-- 基本信息 -->
            <div class="flex-1 min-w-0">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <h3 class="text-xl font-bold text-slate-900">
                    {{ character.name || '未命名角色' }}
                  </h3>
                  <p v-if="character.identity" class="text-sm text-indigo-500 font-medium mt-1">
                    {{ character.identity }}
                  </p>
                </div>
                <!-- 编辑按钮 -->
                <n-button
                  v-if="editable"
                  text
                  type="primary"
                  size="small"
                  @click="handleEditCharacter(character)">
                  编辑
                </n-button>
              </div>

              <!-- 分组标签 -->
              <div v-if="character.group_type" class="mt-2">
                <n-tag type="info" size="small">{{ character.group_type }}</n-tag>
              </div>
            </div>
          </div>

          <!-- 详细信息 -->
          <dl class="space-y-3 text-sm text-slate-600">
            <!-- 出现周期 -->
            <div v-if="character.appearance_period" class="bg-blue-50 p-3 rounded-lg">
              <dt class="font-semibold text-blue-800 mb-1 flex items-center gap-1">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd" />
                </svg>
                出现周期
              </dt>
              <dd class="leading-6 text-blue-900">{{ character.appearance_period }}</dd>
            </div>

            <!-- 性格 -->
            <div v-if="character.personality">
              <dt class="font-semibold text-slate-800 mb-1">性格</dt>
              <dd class="leading-6">{{ character.personality }}</dd>
            </div>

            <!-- 目标 -->
            <div v-if="character.goals">
              <dt class="font-semibold text-slate-800 mb-1">目标</dt>
              <dd class="leading-6">{{ character.goals }}</dd>
            </div>

            <!-- 能力 -->
            <div v-if="character.abilities">
              <dt class="font-semibold text-slate-800 mb-1">能力</dt>
              <dd class="leading-6">{{ character.abilities }}</dd>
            </div>

            <!-- 与主角的关系 -->
            <div v-if="character.relationship_to_protagonist">
              <dt class="font-semibold text-slate-800 mb-1">与主角的关系</dt>
              <dd class="leading-6">{{ character.relationship_to_protagonist }}</dd>
            </div>
          </dl>
        </div>
      </article>

      <!-- 空状态 -->
      <div
        v-if="!filteredCharacters.length"
        class="col-span-full bg-white/95 rounded-2xl border border-dashed border-slate-300 p-10 text-center text-slate-400">
        {{ selectedGroup ? `暂无"${selectedGroup}"分组的角色` : '暂无角色信息' }}
      </div>
    </div>

    <!-- 角色编辑抽屉 -->
    <CharacterEditDrawer
      :key="editingCharacter?.id || 'new'"
      v-model="showEditDrawer"
      :character="editingCharacter"
      :project-id="projectId"
      :available-groups="allGroups"
      @save="handleCharacterSaved" />

    <!-- 分组管理对话框 -->
    <GroupManageDialog
      v-model="showGroupManage"
      :groups="allGroups"
      :characters="charactersWithId"
      :project-id="projectId"
      @refresh="refreshGroups"
      @add-custom-group="handleAddCustomGroup" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineEmits, defineProps, ref, onMounted } from 'vue'
import { NSelect, NButton, NTag, useMessage } from 'naive-ui'
import CharacterEditDrawer from './CharacterEditDrawer.vue'
import GroupManageDialog from './GroupManageDialog.vue'
import type { Character } from '@/types/character'
import { getCharacterGroups } from '@/api/character'
import { API_BASE_URL } from '@/api/novel'
const message = useMessage()

interface CharacterItem {
  id?: number
  name?: string
  identity?: string
  personality?: string
  goals?: string
  abilities?: string
  relationship_to_protagonist?: string
  image_path?: string
  group_type?: string
  appearance_period?: string
}

const props = defineProps<{
  data: { characters?: CharacterItem[] } | null
  editable?: boolean
  projectId: string
}>()

const emit = defineEmits<{
  (e: 'edit', payload: { field: string; title: string; value: any }): void
  (e: 'refresh'): void
}>()

const selectedGroup = ref('')
const showEditDrawer = ref(false)
const showGroupManage = ref(false)
const editingCharacter = ref<Character | null>(null)
const availableGroups = ref<string[]>([])
const customGroups = ref<string[]>([]) // 用户自定义添加的分组（还未被任何角色使用）

// 将CharacterItem转换为Character类型(确保有id)
const charactersWithId = computed(() => {
  return (props.data?.characters || [])
    .filter((c): c is Character => typeof c.id === 'number')
    .map(c => ({
      ...c,
      project_id: props.projectId,
      position: 0
    })) as Character[]
})

const characters = computed(() => props.data?.characters || [])

// 合并后端返回的分组和用户自定义的分组
const allGroups = computed(() => {
  const merged = [...new Set([...availableGroups.value, ...customGroups.value])]
  return merged.sort()
})

// 分组筛选选项
const groupFilterOptions = computed(() => {
  return [
    { label: '全部分组', value: '' },
    ...allGroups.value.map(g => ({ label: g, value: g }))
  ]
})

// 筛选后的角色列表
const filteredCharacters = computed(() => {
  if (!selectedGroup.value) {
    return charactersWithId.value
  }
  return charactersWithId.value.filter(c => c.group_type === selectedGroup.value)
})

// 获取图片URL
const getImageUrl = (path: string) => {
  if (path.startsWith('http')) return path
  return `${API_BASE_URL}${path}`
}

// 处理图片加载错误
const handleImageError = (e: Event) => {
  const img = e.target as HTMLImageElement
  img.style.display = 'none'
}

// 打开编辑抽屉
const handleEditCharacter = (character: Character) => {
  console.log('Opening edit drawer for:', character.name, 'id:', character.id)

  // 简单直接：设置角色并打开抽屉
  // key 属性会确保切换角色时组件重建
  editingCharacter.value = { ...character }
  showEditDrawer.value = true
}

// 角色保存后的回调
const handleCharacterSaved = () => {
  message.success('角色信息已更新')
  emit('refresh')
  refreshGroups()
}

// 处理添加自定义分组
const handleAddCustomGroup = (groupName: string) => {
  if (!customGroups.value.includes(groupName)) {
    customGroups.value.push(groupName)
  }
}

// 刷新分组列表
const refreshGroups = async () => {
  if (!props.projectId) return

  try {
    const response = await getCharacterGroups(props.projectId)
    availableGroups.value = response.groups

    // 清理已经在后端存在的自定义分组
    customGroups.value = customGroups.value.filter(g => !response.groups.includes(g))
  } catch (error: any) {
    console.error('获取分组列表失败:', error)
  }
}

// 原有的编辑函数
const emitEdit = (field: string, title: string, value: any) => {
  if (!props.editable) return
  emit('edit', { field, title, value })
}

// 组件挂载时加载分组
onMounted(() => {
  refreshGroups()
})
</script>

<script lang="ts">
import { defineComponent } from 'vue'

export default defineComponent({
  name: 'CharactersSection'
})
</script>

<style scoped>
/* 组件样式已通过Tailwind实现 */
</style>
