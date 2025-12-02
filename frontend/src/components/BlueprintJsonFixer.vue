<template>
  <div class="p-8 bg-white rounded-2xl shadow-2xl fade-in">
    <h2 class="text-2xl font-bold text-center text-gray-800 mb-4">JSON 格式修复</h2>

    <!-- 错误信息 -->
    <div class="mb-6 p-4 bg-red-50 rounded-lg border border-red-200">
      <div class="flex items-start">
        <svg class="w-5 h-5 text-red-500 mt-0.5 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"></path>
        </svg>
        <div>
          <h3 class="font-semibold text-red-800">{{ segmentDisplayName }} 解析失败</h3>
          <p class="text-sm text-red-700 mt-1">{{ errorMessage }}</p>
          <p v-if="errorPosition !== null" class="text-xs text-red-600 mt-1">
            错误位置：第 {{ errorPosition }} 个字符附近
          </p>
        </div>
      </div>
    </div>

    <!-- AI 提示信息 -->
    <div class="mb-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
      <p class="text-sm text-blue-800">
        <svg class="inline w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>
        </svg>
        {{ aiMessage }}
      </p>
    </div>

    <!-- JSON 编辑器 -->
    <div class="mb-6">
      <label class="block text-sm font-medium text-gray-700 mb-2">
        请修复以下 JSON 内容：
      </label>
      <div class="relative">
        <textarea
          v-model="editedJson"
          class="w-full h-96 p-4 font-mono text-sm border rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 resize-none"
          :class="{ 'border-red-500': jsonError, 'border-gray-300': !jsonError }"
          spellcheck="false"
          @input="validateJson"
        ></textarea>
        <!-- JSON 验证状态 -->
        <div
          class="absolute bottom-3 right-3 px-2 py-1 rounded text-xs font-medium"
          :class="jsonError ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'"
        >
          {{ jsonError || 'JSON 格式正确' }}
        </div>
      </div>
    </div>

    <!-- 已生成的部分 -->
    <div v-if="hasPartialBlueprint" class="mb-6">
      <details class="bg-gray-50 rounded-lg">
        <summary class="p-4 cursor-pointer font-medium text-gray-700 hover:bg-gray-100 rounded-lg">
          已成功生成的部分（{{ partialSegmentCount }} 段）
        </summary>
        <div class="p-4 border-t border-gray-200">
          <pre class="text-xs font-mono text-gray-600 overflow-auto max-h-48">{{ formattedPartialBlueprint }}</pre>
        </div>
      </details>
    </div>

    <!-- 加载状态 -->
    <div v-if="isSubmitting" class="text-center py-8">
      <div class="relative mx-auto mb-4 w-16 h-16">
        <div class="absolute inset-0 border-4 border-indigo-100 rounded-full"></div>
        <div class="absolute inset-0 border-4 border-transparent border-t-indigo-500 rounded-full animate-spin"></div>
      </div>
      <p class="text-gray-600">正在继续生成...</p>
    </div>

    <!-- 操作按钮 -->
    <div v-else class="flex justify-center space-x-4">
      <button
        @click="$emit('cancel')"
        class="px-6 py-2 text-gray-700 bg-gray-200 rounded-full hover:bg-gray-300 transition-colors"
      >
        取消
      </button>
      <button
        @click="formatJson"
        class="px-6 py-2 text-indigo-700 bg-indigo-100 rounded-full hover:bg-indigo-200 transition-colors"
      >
        格式化
      </button>
      <button
        @click="submitFix"
        :disabled="!!jsonError"
        class="px-6 py-2 text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full hover:from-indigo-600 hover:to-purple-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
      >
        修复并继续生成
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { BlueprintGenerationNeedsFixResponse } from '@/api/novel'

interface Props {
  fixData: BlueprintGenerationNeedsFixResponse
}

const props = defineProps<Props>()

const emit = defineEmits<{
  cancel: []
  submit: [fixedData: Record<string, any>]
}>()

const editedJson = ref('')
const jsonError = ref<string | null>(null)
const isSubmitting = ref(false)

// 段名称映射
const segmentNameMap: Record<string, string> = {
  basic: '基础信息',
  world_setting: '世界观设定',
  characters: '角色',
  relationships: '角色关系',
  chapter_outline: '章节大纲',
}

const segmentDisplayName = computed(() => {
  const name = props.fixData.segment_name
  if (name.startsWith('chapter_outline_batch_')) {
    const batchNum = name.replace('chapter_outline_batch_', '')
    return `章节大纲（第 ${batchNum} 批）`
  }
  return segmentNameMap[name] || name
})

const errorMessage = computed(() => props.fixData.error_message)
const errorPosition = computed(() => props.fixData.error_position)
const aiMessage = computed(() => props.fixData.ai_message)

const hasPartialBlueprint = computed(() => {
  return Object.keys(props.fixData.partial_blueprint).length > 0
})

const partialSegmentCount = computed(() => {
  const bp = props.fixData.partial_blueprint
  let count = 0
  if (bp.title) count++
  if (bp.world_setting) count++
  if (bp.characters?.length) count++
  if (bp.relationships?.length) count++
  if (bp.chapter_outline?.length) count++
  return count
})

const formattedPartialBlueprint = computed(() => {
  try {
    return JSON.stringify(props.fixData.partial_blueprint, null, 2)
  } catch {
    return '{}'
  }
})

// 初始化编辑器内容
onMounted(() => {
  editedJson.value = props.fixData.raw_response
  validateJson()
})

// 验证 JSON 格式
const validateJson = () => {
  try {
    JSON.parse(editedJson.value)
    jsonError.value = null
  } catch (e) {
    if (e instanceof SyntaxError) {
      jsonError.value = e.message
    } else {
      jsonError.value = '未知错误'
    }
  }
}

// 格式化 JSON
const formatJson = () => {
  try {
    const parsed = JSON.parse(editedJson.value)
    editedJson.value = JSON.stringify(parsed, null, 2)
    jsonError.value = null
  } catch (e) {
    // 如果解析失败，保持原样
  }
}

// 提交修复
const submitFix = () => {
  if (jsonError.value) return

  try {
    const fixedData = JSON.parse(editedJson.value)
    isSubmitting.value = true
    emit('submit', fixedData)
  } catch (e) {
    jsonError.value = '无法解析 JSON'
  }
}

// 暴露方法供父组件调用
defineExpose({
  resetSubmitting: () => {
    isSubmitting.value = false
  }
})
</script>

<style scoped>
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.fade-in {
  animation: fadeIn 0.6s ease-out;
}

textarea {
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', 'Courier New', monospace;
}
</style>
