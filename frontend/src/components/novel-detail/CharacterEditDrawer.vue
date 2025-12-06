<template>
  <n-drawer
    v-model:show="visible"
    :width="600"
    placement="right"
    @after-leave="handleClose">
    <n-drawer-content :title="isEdit ? '编辑角色' : '新建角色'" closable>
      <n-form
        ref="formRef"
        :model="formData"
        :rules="rules"
        label-placement="left"
        label-width="120"
        class="px-4">
        <!-- 角色图片 -->
        <n-form-item label="角色图片">
          <div class="w-full">
            <!-- 已有图片预览 -->
            <div v-if="imageUrl" class="relative w-32 h-32 mb-2">
              <img :src="imageUrl" class="w-full h-full object-cover rounded-lg border" alt="角色图片" />
              <div class="absolute top-1 right-1">
                <n-button size="small" circle secondary @click="handleRemoveImage">
                  <template #icon>
                    <n-icon>
                      <Close />
                    </n-icon>
                  </template>
                </n-button>
              </div>
            </div>

            <!-- 上传按钮 -->
            <n-upload
              v-else
              :max="1"
              :show-file-list="false"
              :custom-request="handleImageUpload"
              accept="image/jpeg,image/jpg,image/png,image/webp"
              @before-upload="beforeImageUpload">
              <n-button>
                <template #icon>
                  <n-icon>
                    <Add />
                  </n-icon>
                </template>
                选择图片
              </n-button>
            </n-upload>

            <div class="text-xs text-gray-500 mt-2">
              支持 JPG、PNG、WEBP 格式,大小不超过 2MB
            </div>
          </div>
        </n-form-item>

        <!-- 角色姓名 -->
        <n-form-item label="姓名" path="name">
          <n-input v-model:value="formData.name" placeholder="请输入角色姓名" clearable />
        </n-form-item>

        <!-- 身份 -->
        <n-form-item label="身份" path="identity">
          <n-input v-model:value="formData.identity" placeholder="例如:女主角、男主角、反派" clearable />
        </n-form-item>

        <!-- 分组 -->
        <n-form-item label="分组" path="group_type">
          <n-select
            v-model:value="formData.group_type"
            placeholder="选择或输入分组"
            filterable
            tag
            clearable
            :options="groupOptions" />
        </n-form-item>

        <!-- 出现周期 -->
        <n-form-item label="出现周期" path="appearance_period">
          <n-input
            v-model:value="formData.appearance_period"
            type="textarea"
            :rows="2"
            placeholder="例如:第1-50章,贯穿全文"
            clearable />
        </n-form-item>

        <!-- 性格 -->
        <n-form-item label="性格" path="personality">
          <n-input
            v-model:value="formData.personality"
            type="textarea"
            :rows="3"
            placeholder="请描述角色性格特点"
            clearable />
        </n-form-item>

        <!-- 目标 -->
        <n-form-item label="目标" path="goals">
          <n-input
            v-model:value="formData.goals"
            type="textarea"
            :rows="3"
            placeholder="请描述角色的目标或追求"
            clearable />
        </n-form-item>

        <!-- 能力 -->
        <n-form-item label="能力" path="abilities">
          <n-input
            v-model:value="formData.abilities"
            type="textarea"
            :rows="3"
            placeholder="请描述角色的特殊能力或技能"
            clearable />
        </n-form-item>

        <!-- 与主角的关系 -->
        <n-form-item label="与主角的关系" path="relationship_to_protagonist">
          <n-input
            v-model:value="formData.relationship_to_protagonist"
            type="textarea"
            :rows="3"
            placeholder="请描述角色与主角的关系"
            clearable />
        </n-form-item>
      </n-form>

      <template #footer>
        <div class="flex justify-end gap-3">
          <n-button @click="handleClose">取消</n-button>
          <n-button type="primary" :loading="loading" @click="handleSubmit">
            保存
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect } from 'vue'
import {
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NButton,
  NUpload,
  NIcon,
  useMessage,
  type FormInst,
  type FormRules,
  type UploadCustomRequestOptions
} from 'naive-ui'
import { Add, Close } from '@vicons/ionicons5'
import type { Character, CharacterUpdate } from '@/types/character'
import { updateCharacter, uploadCharacterImage, deleteCharacterImage } from '@/api/character'
import { API_BASE_URL } from '@/api/novel'

interface Props {
  modelValue: boolean
  character: Character | null
  projectId: string
  availableGroups: string[]
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'save', character: Character): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const message = useMessage()
const formRef = ref<FormInst | null>(null)
const loading = ref(false)
const imageUrl = ref<string>('')
const pendingImageFile = ref<File | null>(null)

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const isEdit = computed(() => !!props.character)

const groupOptions = computed(() => {
  return props.availableGroups.map(g => ({ label: g, value: g }))
})

const formData = ref<CharacterUpdate>({
  name: '',
  identity: '',
  personality: '',
  goals: '',
  abilities: '',
  relationship_to_protagonist: '',
  group_type: '',
  appearance_period: ''
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入角色姓名', trigger: 'blur' }]
}

const resetForm = () => {
  formData.value = {
    name: '',
    identity: '',
    personality: '',
    goals: '',
    abilities: '',
    relationship_to_protagonist: '',
    group_type: '',
    appearance_period: ''
  }
  imageUrl.value = ''
  pendingImageFile.value = null
}

// 监听character变化,初始化表单
// 使用 watchEffect 自动追踪依赖，比 watch 更可靠
watchEffect(() => {
  const char = props.character

  if (!char) {
    console.log('Character is null, keeping current form data')
    return
  }

  console.log('Initializing form data for character:', {
    id: char.id,
    name: char.name,
    hasImagePath: !!char.image_path
  })

  // 直接赋值，watchEffect 会自动追踪所有依赖
  formData.value = {
    name: char.name,
    identity: char.identity || '',
    personality: char.personality || '',
    goals: char.goals || '',
    abilities: char.abilities || '',
    relationship_to_protagonist: char.relationship_to_protagonist || '',
    group_type: char.group_type || '',
    appearance_period: char.appearance_period || ''
  }

  imageUrl.value = char.image_path ? `${API_BASE_URL}${char.image_path}` : ''

  console.log('Form data initialized successfully:', {
    name: formData.value.name,
    groupType: formData.value.group_type
  })
})

const beforeImageUpload = (options: { file: { file: File | null }; fileList: any[] }) => {
  const file = options.file.file
  if (!file) return false

  const isImage = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'].includes(file.type)
  const isLt2M = file.size / 1024 / 1024 < 2

  if (!isImage) {
    message.error('只支持 JPG、PNG、WEBP 格式的图片!')
    return false
  }
  if (!isLt2M) {
    message.error('图片大小不能超过 2MB!')
    return false
  }
  return true
}

const handleImageUpload = (options: UploadCustomRequestOptions) => {
  const file = options.file.file as File

  // 预览图片
  const reader = new FileReader()
  reader.onload = (e) => {
    imageUrl.value = e.target?.result as string
  }
  reader.readAsDataURL(file)

  // 保存文件待提交时上传
  pendingImageFile.value = file

  // 调用 onFinish 表示上传完成
  options.onFinish()
}

const handleRemoveImage = async () => {
  if (!props.character?.id) {
    imageUrl.value = ''
    pendingImageFile.value = null
    return
  }

  try {
    await deleteCharacterImage(props.projectId, props.character.id)
    imageUrl.value = ''
    pendingImageFile.value = null
    formData.value.image_path = undefined
    message.success('图片已删除')
  } catch (error: any) {
    message.error(error.message || '删除图片失败')
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch {
    return
  }

  if (!props.character?.id) {
    message.warning('角色ID不存在,无法保存')
    return
  }

  loading.value = true

  try {
    // 1. 先上传图片(如果有)
    if (pendingImageFile.value) {
      const uploadResult = await uploadCharacterImage(
        props.projectId,
        props.character.id,
        pendingImageFile.value
      )
      formData.value.image_path = uploadResult.image_path
    }

    // 2. 更新角色信息
    const updatedCharacter = await updateCharacter(
      props.projectId,
      props.character.id,
      formData.value
    )

    message.success('保存成功')
    emit('save', updatedCharacter)
    handleClose()
  } catch (error: any) {
    message.error(error.message || '保存失败')
  } finally {
    loading.value = false
  }
}

const handleClose = () => {
  visible.value = false
  // 关闭时重置表单
  setTimeout(() => {
    resetForm()
  }, 300) // 等待抽屉动画完成后再重置
}
</script>

<script lang="ts">
import { defineComponent } from 'vue'

export default defineComponent({
  name: 'CharacterEditDrawer'
})
</script>
