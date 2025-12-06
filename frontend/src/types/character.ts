/**
 * 角色相关类型定义
 */

export interface Character {
  id: number
  project_id: string
  name: string
  identity?: string
  personality?: string
  goals?: string
  abilities?: string
  relationship_to_protagonist?: string
  image_path?: string
  group_type?: string
  appearance_period?: string
  position: number
}

export interface CharacterUpdate {
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

export interface CharacterGroupsResponse {
  groups: string[]
}

export interface RenameGroupRequest {
  old_group: string
  new_group: string
}

export interface UploadImageResponse {
  status: string
  image_path: string
}
