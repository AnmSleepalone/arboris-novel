/**
 * 角色管理 API 调用模块
 */

import type {
  Character,
  CharacterUpdate,
  CharacterGroupsResponse,
  RenameGroupRequest,
  UploadImageResponse
} from '@/types/character'
import { API_BASE_URL, API_PREFIX } from './novel'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

// 统一的请求处理函数
const request = async (url: string, options: RequestInit = {}) => {
  const authStore = useAuthStore()
  const headers = new Headers(options.headers)

  // 只在非FormData时设置Content-Type
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  if (authStore.isAuthenticated && authStore.token) {
    headers.set('Authorization', `Bearer ${authStore.token}`)
  }

  const response = await fetch(url, { ...options, headers })

  if (response.status === 401) {
    authStore.logout()
    router.push('/login')
    throw new Error('会话已过期，请重新登录')
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `请求失败，状态码: ${response.status}`)
  }

  return response.json()
}

/**
 * 更新角色信息
 */
export const updateCharacter = async (
  projectId: string,
  characterId: number,
  data: CharacterUpdate
): Promise<Character> => {
  return request(`${API_BASE_URL}${API_PREFIX}/novels/${projectId}/characters/${characterId}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  })
}

/**
 * 上传角色图片
 */
export const uploadCharacterImage = async (
  projectId: string,
  characterId: number,
  file: File
): Promise<UploadImageResponse> => {
  const formData = new FormData()
  formData.append('file', file)

  return request(`${API_BASE_URL}${API_PREFIX}/novels/${projectId}/characters/${characterId}/image`, {
    method: 'POST',
    body: formData
  })
}

/**
 * 删除角色图片
 */
export const deleteCharacterImage = async (
  projectId: string,
  characterId: number
): Promise<{ status: string; message: string }> => {
  return request(`${API_BASE_URL}${API_PREFIX}/novels/${projectId}/characters/${characterId}/image`, {
    method: 'DELETE'
  })
}

/**
 * 获取项目中所有角色分组
 */
export const getCharacterGroups = async (
  projectId: string
): Promise<CharacterGroupsResponse> => {
  return request(`${API_BASE_URL}${API_PREFIX}/novels/${projectId}/characters/groups`, {
    method: 'GET'
  })
}

/**
 * 重命名角色分组
 */
export const renameCharacterGroup = async (
  projectId: string,
  data: RenameGroupRequest
): Promise<{ status: string; message: string; affected_count: number }> => {
  return request(`${API_BASE_URL}${API_PREFIX}/novels/${projectId}/characters/groups/rename`, {
    method: 'POST',
    body: JSON.stringify(data)
  })
}
