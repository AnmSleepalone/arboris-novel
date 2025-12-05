/**
 * 小说四层大纲结构类型定义
 * 层级: Project -> Part -> Volume -> Chapter
 */

/**
 * 篇(Part)基础信息
 */
export interface Part {
  id: number
  project_id: string
  part_number: number
  title: string
  description?: string
  position: number
}

/**
 * 篇创建请求
 */
export interface PartCreate {
  title: string
  description?: string
}

/**
 * 篇更新请求
 */
export interface PartUpdate {
  title?: string
  description?: string
}

/**
 * 卷(Volume)基础信息
 */
export interface Volume {
  id: number
  project_id: string
  part_id: number
  volume_number: number
  title: string
  description?: string
  position: number
}

/**
 * 卷创建请求
 */
export interface VolumeCreate {
  title: string
  description?: string
}

/**
 * 卷更新请求
 */
export interface VolumeUpdate {
  title?: string
  description?: string
}

/**
 * 章节大纲详细信息
 */
export interface ChapterOutlineDetail {
  id: number
  volume_id: number
  chapter_number: number
  title: string
  summary?: string
}

/**
 * 包含章节列表的卷
 */
export interface VolumeWithChapters extends Volume {
  chapters: ChapterOutlineDetail[]
}

/**
 * 包含卷列表的篇
 */
export interface PartWithVolumes extends Part {
  volumes: VolumeWithChapters[]
}

/**
 * 树形大纲响应
 */
export interface OutlineTreeResponse {
  parts: PartWithVolumes[]
}

/**
 * 重排序请求
 */
export interface ReorderRequest {
  ids: number[]
}

/**
 * 移动卷请求
 */
export interface MoveVolumeRequest {
  target_part_id: number
}

/**
 * 移动章节请求
 */
export interface MoveChapterRequest {
  target_volume_id: number
  new_chapter_number: number
}

/**
 * LLM 生成响应
 */
export interface GenerateResponse<T> {
  status: string
  data: T
  ai_message: string
}

/**
 * Part 生成结果
 */
export interface PartsGenerationData {
  parts: Array<{
    part_number: number
    title: string
    description: string
    theme: string
    estimated_chapters: number
  }>
  total_parts: number
  rationale: string
}

/**
 * Volume 生成结果
 */
export interface VolumesGenerationData {
  volumes: Array<{
    volume_number: number
    title: string
    description: string
    conflict: string
    estimated_chapters: number
  }>
  total_volumes: number
  rationale: string
}

/**
 * 树节点类型(用于 Naive UI Tree 组件)
 */
export type OutlineNodeType = 'part' | 'volume' | 'chapter'

/**
 * 树节点数据
 */
export interface OutlineTreeNode {
  key: string
  label: string
  type: OutlineNodeType
  data: Part | Volume | ChapterOutlineDetail
  children?: OutlineTreeNode[]
  prefix?: () => any // 用于自定义图标
  suffix?: () => any // 用于操作按钮
}

/**
 * 节点操作菜单项
 */
export interface NodeAction {
  label: string
  key: string
  icon?: () => any
  disabled?: boolean
  show?: boolean
}
