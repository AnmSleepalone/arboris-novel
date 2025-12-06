<template>
  <n-modal
    v-model:show="visible"
    preset="dialog"
    title="管理角色分组"
    :style="{ width: '500px' }"
    @after-leave="handleClose">
    <div class="space-y-4">
      <!-- 现有分组列表 -->
      <div v-if="groups.length > 0">
        <div class="text-sm text-gray-600 mb-2">现有分组:</div>
        <div class="space-y-2">
          <div
            v-for="(group, index) in groups"
            :key="group"
            class="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
            <div class="flex items-center gap-2">
              <n-tag type="info">{{ group }}</n-tag>
              <span class="text-xs text-gray-500">
                ({{ getGroupCount(group) }} 个角色)
              </span>
            </div>
            <div class="flex items-center gap-2">
              <n-button
                text
                type="primary"
                size="small"
                @click="startRename(group, index)">
                重命名
              </n-button>
              <n-button
                text
                type="error"
                size="small"
                @click="handleDeleteGroup(group)">
                删除
              </n-button>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="text-center py-8 text-gray-400">
        暂无分组
      </div>

      <!-- 添加新分组 -->
      <n-divider />
      <div>
        <div class="text-sm text-gray-600 mb-2">添加新分组:</div>
        <div class="flex gap-2">
          <n-input
            v-model:value="newGroupName"
            placeholder="输入新分组名称"
            clearable
            @keyup.enter="handleAddGroup" />
          <n-button type="primary" @click="handleAddGroup">添加</n-button>
        </div>
      </div>
    </div>

    <template #action>
      <n-button @click="handleClose">关闭</n-button>
    </template>
  </n-modal>

  <!-- 重命名对话框 -->
  <n-modal
    v-model:show="renameDialogVisible"
    preset="dialog"
    title="重命名分组"
    :style="{ width: '400px' }">
    <n-form @submit.prevent="confirmRename">
      <n-form-item label="新名称">
        <n-input
          v-model:value="renameNewName"
          placeholder="输入新的分组名称"
          clearable
          @keyup.enter="confirmRename" />
      </n-form-item>
    </n-form>

    <template #action>
      <n-space>
        <n-button @click="renameDialogVisible = false">取消</n-button>
        <n-button type="primary" :loading="renaming" @click="confirmRename">
          确定
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NModal,
  NButton,
  NTag,
  NDivider,
  NInput,
  NForm,
  NFormItem,
  NSpace,
  useDialog,
  useMessage
} from 'naive-ui'
import { renameCharacterGroup } from '@/api/character'
import type { Character } from '@/types/character'

interface Props {
  modelValue: boolean
  groups: string[]
  characters: Character[]
  projectId: string
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'refresh'): void
  (e: 'add-custom-group', groupName: string): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const message = useMessage()
const dialog = useDialog()
const newGroupName = ref('')
const renameDialogVisible = ref(false)
const renameOldName = ref('')
const renameNewName = ref('')
const renaming = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

// 获取每个分组的角色数量
const getGroupCount = (group: string) => {
  return props.characters.filter(c => c.group_type === group).length
}

// 添加新分组
const handleAddGroup = () => {
  const name = newGroupName.value.trim()
  if (!name) {
    message.warning('请输入分组名称')
    return
  }

  if (props.groups.includes(name)) {
    message.warning('该分组已存在')
    return
  }

  // 通知父组件添加自定义分组
  emit('add-custom-group', name)
  message.success(`分组 "${name}" 已添加，现在可以在编辑角色时使用`)
  newGroupName.value = ''
}

// 开始重命名
const startRename = (group: string, index: number) => {
  renameOldName.value = group
  renameNewName.value = group
  renameDialogVisible.value = true
}

// 确认重命名
const confirmRename = async () => {
  const oldName = renameOldName.value
  const newName = renameNewName.value.trim()

  if (!newName) {
    message.warning('请输入新名称')
    return
  }

  if (oldName === newName) {
    renameDialogVisible.value = false
    return
  }

  if (props.groups.includes(newName)) {
    message.warning('该分组名称已存在')
    return
  }

  renaming.value = true

  try {
    const result = await renameCharacterGroup(props.projectId, {
      old_group: oldName,
      new_group: newName
    })

    message.success(result.message || `已更新 ${result.affected_count} 个角色的分组`)
    renameDialogVisible.value = false
    emit('refresh')
  } catch (error: any) {
    message.error(error.message || '重命名失败')
  } finally {
    renaming.value = false
  }
}

// 删除分组
const handleDeleteGroup = async (group: string) => {
  const count = getGroupCount(group)

  dialog.warning({
    title: '警告',
    content: `确定要删除分组 "${group}" 吗? 这将清空 ${count} 个角色的分组信息。`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        // 重命名为空字符串即删除
        await renameCharacterGroup(props.projectId, {
          old_group: group,
          new_group: ''
        })
        message.success('分组已删除')
        emit('refresh')
      } catch (error: any) {
        message.error(error.message || '删除失败')
      }
    }
  })
}

const handleClose = () => {
  visible.value = false
  newGroupName.value = ''
}
</script>

<script lang="ts">
import { defineComponent } from 'vue'

export default defineComponent({
  name: 'GroupManageDialog'
})
</script>

<style scoped>
/* 组件样式 */
</style>
