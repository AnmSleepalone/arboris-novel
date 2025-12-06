from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChoiceOption(BaseModel):
    """前端选择项描述，用于动态 UI 控件。"""

    id: str
    label: str


class UIControl(BaseModel):
    """描述前端应渲染的组件类型与配置。"""

    type: str = Field(..., description="控件类型，如 single_choice/text_input")
    options: Optional[List[ChoiceOption]] = Field(default=None, description="可选项列表")
    placeholder: Optional[str] = Field(default=None, description="输入提示文案")


class ConverseResponse(BaseModel):
    """概念对话接口的统一返回体。"""

    ai_message: str
    ui_control: UIControl
    conversation_state: Dict[str, Any]
    is_complete: bool = False
    ready_for_blueprint: Optional[bool] = None


class ConverseRequest(BaseModel):
    """概念对话接口的请求体。"""

    user_input: Dict[str, Any]
    conversation_state: Dict[str, Any]


class ChapterGenerationStatus(str, Enum):
    NOT_GENERATED = "not_generated"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    SELECTING = "selecting"
    FAILED = "failed"
    EVALUATION_FAILED = "evaluation_failed"
    WAITING_FOR_CONFIRM = "waiting_for_confirm"
    SUCCESSFUL = "successful"


class ChapterOutline(BaseModel):
    chapter_number: int
    title: str
    summary: Optional[str] = None


class Chapter(ChapterOutline):
    real_summary: Optional[str] = None
    content: Optional[str] = None
    versions: Optional[List[str]] = None
    evaluation: Optional[str] = None
    generation_status: ChapterGenerationStatus = ChapterGenerationStatus.NOT_GENERATED
    word_count: Optional[int] = None


class Relationship(BaseModel):
    character_from: str
    character_to: str
    description: str


class Blueprint(BaseModel):
    title: str
    target_audience: str = ""
    genre: str = ""
    style: str = ""
    tone: str = ""
    one_sentence_summary: str = ""
    full_synopsis: str = ""
    world_setting: Dict[str, Any] = {}
    characters: List[Dict[str, Any]] = []
    relationships: List[Relationship] = []
    chapter_outline: List[ChapterOutline] = []


class NovelProject(BaseModel):
    id: str
    user_id: int
    title: str
    initial_prompt: str
    conversation_history: List[Dict[str, Any]] = []
    blueprint: Optional[Blueprint] = None
    chapters: List[Chapter] = []

    class Config:
        from_attributes = True


class NovelProjectSummary(BaseModel):
    id: str
    title: str
    genre: str
    last_edited: str
    completed_chapters: int
    total_chapters: int


class BlueprintGenerationResponse(BaseModel):
    """蓝图生成成功的响应。"""
    blueprint: Blueprint
    ai_message: str
    status: str = "success"


class BlueprintGenerationNeedsFixResponse(BaseModel):
    """蓝图生成需要用户修复时的响应。"""
    status: str = "needs_fix"
    segment_name: str = Field(..., description="失败的段名称")
    segment_index: int = Field(..., description="失败的段索引 (1-5)")
    raw_response: str = Field(..., description="LLM 原始响应")
    error_message: str = Field(..., description="错误详情")
    error_position: Optional[int] = Field(None, description="错误位置（字符索引）")
    partial_blueprint: Dict[str, Any] = Field(..., description="已成功生成的部分蓝图")
    ai_message: str = Field(..., description="给用户的提示信息")
    # 用于恢复生成的上下文
    generation_context: Dict[str, Any] = Field(..., description="生成上下文，用于恢复继续生成")


class BlueprintFixAndContinueRequest(BaseModel):
    """用户修复 JSON 后继续生成的请求。"""
    fixed_data: Dict[str, Any] = Field(..., description="用户修复后的 JSON 数据")
    segment_name: str = Field(..., description="修复的段名称")
    partial_blueprint: Dict[str, Any] = Field(..., description="已成功生成的部分蓝图")
    generation_context: Dict[str, Any] = Field(..., description="生成上下文")


class ChapterGenerationResponse(BaseModel):
    ai_message: str
    chapter_versions: List[Dict[str, Any]]


class NovelSectionType(str, Enum):
    OVERVIEW = "overview"
    WORLD_SETTING = "world_setting"
    CHARACTERS = "characters"
    RELATIONSHIPS = "relationships"
    CHAPTER_OUTLINE = "chapter_outline"
    CHAPTERS = "chapters"


class NovelSectionResponse(BaseModel):
    section: NovelSectionType
    data: Dict[str, Any]


class GenerateChapterRequest(BaseModel):
    chapter_number: int
    writing_notes: Optional[str] = Field(default=None, description="章节额外写作指令")


class SelectVersionRequest(BaseModel):
    chapter_number: int
    version_index: int


class EvaluateChapterRequest(BaseModel):
    chapter_number: int


class UpdateChapterOutlineRequest(BaseModel):
    chapter_number: int
    title: str
    summary: str


class DeleteChapterRequest(BaseModel):
    chapter_numbers: List[int]


class GenerateOutlineRequest(BaseModel):
    start_chapter: int
    num_chapters: int


class BlueprintPatch(BaseModel):
    one_sentence_summary: Optional[str] = None
    full_synopsis: Optional[str] = None
    world_setting: Optional[Dict[str, Any]] = None
    characters: Optional[List[Dict[str, Any]]] = None
    relationships: Optional[List[Relationship]] = None
    chapter_outline: Optional[List[ChapterOutline]] = None


class EditChapterRequest(BaseModel):
    chapter_number: int
    content: str


# ------------------------------------------------------------------
# Part/Volume 相关Schema
# ------------------------------------------------------------------
class PartBase(BaseModel):
    title: str
    description: Optional[str] = None


class PartCreate(PartBase):
    pass


class PartUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class PartSchema(PartBase):
    id: int
    project_id: str
    part_number: int
    position: int

    class Config:
        from_attributes = True


class VolumeBase(BaseModel):
    title: str
    description: Optional[str] = None


class VolumeCreate(VolumeBase):
    pass


class VolumeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class VolumeSchema(VolumeBase):
    id: int
    project_id: str
    part_id: int
    volume_number: int
    position: int

    class Config:
        from_attributes = True


class ChapterOutlineDetail(BaseModel):
    """章节大纲详细信息(包含volume_id)"""
    id: int
    volume_id: int
    chapter_number: int
    title: str
    summary: Optional[str] = None

    class Config:
        from_attributes = True


class VolumeWithChapters(VolumeSchema):
    """包含章节列表的Volume"""
    chapters: List[ChapterOutlineDetail] = []


class PartWithVolumes(PartSchema):
    """包含卷列表的Part"""
    volumes: List[VolumeWithChapters] = []


class OutlineTreeResponse(BaseModel):
    """树形大纲响应"""
    parts: List[PartWithVolumes]


class ReorderRequest(BaseModel):
    """重排序请求"""
    ids: List[int] = Field(..., description="按新顺序排列的ID列表")


class MoveVolumeRequest(BaseModel):
    """移动Volume请求"""
    target_part_id: int


class MoveChapterRequest(BaseModel):
    """移动Chapter请求"""
    target_volume_id: int
    new_chapter_number: int


class ChapterOutlineCreate(BaseModel):
    """创建章节大纲请求"""
    title: str
    summary: Optional[str] = None


class ChapterOutlineUpdate(BaseModel):
    """更新章节大纲请求"""
    title: Optional[str] = None
    summary: Optional[str] = None


# ------------------------------------------------------------------
# Character 相关Schema
# ------------------------------------------------------------------
class CharacterBase(BaseModel):
    """角色基础信息"""
    name: str
    identity: Optional[str] = None
    personality: Optional[str] = None
    goals: Optional[str] = None
    abilities: Optional[str] = None
    relationship_to_protagonist: Optional[str] = None
    image_path: Optional[str] = None
    group_type: Optional[str] = None
    appearance_period: Optional[str] = None


class CharacterCreate(CharacterBase):
    """创建角色请求"""
    pass


class CharacterUpdate(BaseModel):
    """更新角色请求"""
    name: Optional[str] = None
    identity: Optional[str] = None
    personality: Optional[str] = None
    goals: Optional[str] = None
    abilities: Optional[str] = None
    relationship_to_protagonist: Optional[str] = None
    image_path: Optional[str] = None
    group_type: Optional[str] = None
    appearance_period: Optional[str] = None


class CharacterDetail(CharacterBase):
    """角色详情响应"""
    id: int
    project_id: str
    position: int

    class Config:
        from_attributes = True


class CharacterGroupsResponse(BaseModel):
    """角色分组列表响应"""
    groups: List[str]

