import json
import logging
from typing import Dict, List, Any

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.dependencies import get_current_user
from ...db.session import get_session
from ...models import NovelPart
from ...schemas.novel import (
    Blueprint,
    BlueprintFixAndContinueRequest,
    BlueprintGenerationNeedsFixResponse,
    BlueprintGenerationResponse,
    BlueprintPatch,
    Chapter as ChapterSchema,
    CharacterDetail,
    CharacterGroupsResponse,
    CharacterUpdate,
    ChapterOutlineCreate,
    ChapterOutlineDetail,
    ChapterOutlineUpdate,
    ConverseRequest,
    ConverseResponse,
    MoveChapterRequest,
    MoveVolumeRequest,
    NovelProject as NovelProjectSchema,
    NovelProjectSummary,
    NovelSectionResponse,
    NovelSectionType,
    OutlineTreeResponse,
    PartCreate,
    PartSchema,
    PartUpdate,
    ReorderRequest,
    VolumeCreate,
    VolumeSchema,
    VolumeUpdate,
)
from ...schemas.user import UserInDB
from ...services.llm_service import LLMService
from ...services.novel_service import NovelService
from ...services.prompt_service import PromptService
from ...utils.json_utils import remove_think_tags, sanitize_json_like_text, unwrap_markdown_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels", tags=["Novels"])

JSON_RESPONSE_INSTRUCTION = """
IMPORTANT: 你的回复必须是合法的 JSON 对象，并严格包含以下字段：
{
  "ai_message": "string",
  "ui_control": {
    "type": "single_choice | text_input | info_display",
    "options": [
      {"id": "option_1", "label": "string"}
    ],
    "placeholder": "string"
  },
  "conversation_state": {},
  "is_complete": false
}
不要输出额外的文本或解释。
"""


def _ensure_prompt(prompt: str | None, name: str) -> str:
    if not prompt:
        raise HTTPException(status_code=500, detail=f"未配置名为 {name} 的提示词，请联系管理员")
    return prompt


@router.post("", response_model=NovelProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_novel(
    title: str = Body(...),
    initial_prompt: str = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """为当前用户创建一个新的小说项目。"""
    novel_service = NovelService(session)
    project = await novel_service.create_project(current_user.id, title, initial_prompt)
    logger.info("用户 %s 创建项目 %s", current_user.id, project.id)
    return await novel_service.get_project_schema(project.id, current_user.id)


@router.get("", response_model=List[NovelProjectSummary])
async def list_novels(
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> List[NovelProjectSummary]:
    """列出用户的全部小说项目摘要信息。"""
    novel_service = NovelService(session)
    projects = await novel_service.list_projects_for_user(current_user.id)
    logger.info("用户 %s 获取项目列表，共 %s 个", current_user.id, len(projects))
    return projects


@router.get("/{project_id}", response_model=NovelProjectSchema)
async def get_novel(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    novel_service = NovelService(session)
    logger.info("用户 %s 查询项目 %s", current_user.id, project_id)
    return await novel_service.get_project_schema(project_id, current_user.id)


@router.get("/{project_id}/sections/{section}", response_model=NovelSectionResponse)
async def get_novel_section(
    project_id: str,
    section: NovelSectionType,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelSectionResponse:
    novel_service = NovelService(session)
    logger.info("用户 %s 获取项目 %s 的 %s 区段", current_user.id, project_id, section)
    return await novel_service.get_section_data(project_id, current_user.id, section)


@router.get("/{project_id}/chapters/{chapter_number}", response_model=ChapterSchema)
async def get_chapter(
    project_id: str,
    chapter_number: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ChapterSchema:
    novel_service = NovelService(session)
    logger.info("用户 %s 获取项目 %s 第 %s 章", current_user.id, project_id, chapter_number)
    return await novel_service.get_chapter_schema(project_id, current_user.id, chapter_number)


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_novels(
    project_ids: List[str] = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    novel_service = NovelService(session)
    await novel_service.delete_projects(project_ids, current_user.id)
    logger.info("用户 %s 删除项目 %s", current_user.id, project_ids)
    return {"status": "success", "message": f"成功删除 {len(project_ids)} 个项目"}


@router.post("/{project_id}/concept/converse", response_model=ConverseResponse)
async def converse_with_concept(
    project_id: str,
    request: ConverseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ConverseResponse:
    """与概念设计师（LLM）进行对话，引导蓝图筹备。"""
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    history_records = await novel_service.list_conversations(project_id)
    logger.info(
        "项目 %s 概念对话请求，用户 %s，历史记录 %s 条",
        project_id,
        current_user.id,
        len(history_records),
    )
    conversation_history = [
        {"role": record.role, "content": record.content}
        for record in history_records
    ]
    user_content = json.dumps(request.user_input, ensure_ascii=False)
    conversation_history.append({"role": "user", "content": user_content})

    system_prompt = _ensure_prompt(await prompt_service.get_prompt("concept"), "concept")
    system_prompt = f"{system_prompt}\n{JSON_RESPONSE_INSTRUCTION}"

    llm_response = await llm_service.get_llm_response(
        system_prompt=system_prompt,
        conversation_history=conversation_history,
        temperature=0.8,
        user_id=current_user.id,
        timeout=240.0,
    )
    llm_response = remove_think_tags(llm_response)

    try:
        normalized = unwrap_markdown_json(llm_response)
        sanitized = sanitize_json_like_text(normalized)
        parsed = json.loads(sanitized)
    except json.JSONDecodeError as exc:
        logger.exception(
            "Failed to parse concept converse response: project_id=%s user_id=%s error=%s\nOriginal response: %s\nNormalized: %s\nSanitized: %s",
            project_id,
            current_user.id,
            exc,
            llm_response[:1000],
            normalized[:1000] if 'normalized' in locals() else "N/A",
            sanitized[:1000] if 'sanitized' in locals() else "N/A",
        )
        raise HTTPException(
            status_code=500,
            detail=f"概念对话失败，AI 返回的内容格式不正确。请重试或联系管理员。错误详情: {str(exc)}"
        ) from exc

    await novel_service.append_conversation(project_id, "user", user_content)
    await novel_service.append_conversation(project_id, "assistant", normalized)

    logger.info("项目 %s 概念对话完成，is_complete=%s", project_id, parsed.get("is_complete"))

    if parsed.get("is_complete"):
        parsed["ready_for_blueprint"] = True

    parsed.setdefault("conversation_state", parsed.get("conversation_state", {}))
    return ConverseResponse(**parsed)


@router.post("/{project_id}/blueprint/generate")
async def generate_blueprint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> BlueprintGenerationResponse | BlueprintGenerationNeedsFixResponse:
    """根据完整对话生成可执行的小说蓝图（分段生成，避免截断）。

    返回值：
    - 成功时返回 BlueprintGenerationResponse
    - JSON 解析失败时返回 BlueprintGenerationNeedsFixResponse，供用户手动修复
    """
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)
    logger.info("项目 %s 开始生成蓝图（分段模式）", project_id)

    history_records = await novel_service.list_conversations(project_id)
    if not history_records:
        logger.warning("项目 %s 缺少对话历史，无法生成蓝图", project_id)
        raise HTTPException(status_code=400, detail="缺少对话历史，请先完成概念对话后再生成蓝图")

    formatted_history: List[Dict[str, str]] = []
    total_chapters = 20  # 默认章节数

    for record in history_records:
        role = record.role
        content = record.content
        if not role or not content:
            continue
        try:
            normalized = unwrap_markdown_json(content)
            data = json.loads(normalized)
            if role == "user":
                user_value = data.get("value", data)
                if isinstance(user_value, str):
                    formatted_history.append({"role": "user", "content": user_value})
                # 尝试从用户输入中提取章节数量
                if isinstance(data, dict):
                    chapter_info = data.get("chapter_count") or data.get("chapters") or data.get("total_chapters")
                    if chapter_info:
                        try:
                            total_chapters = int(chapter_info)
                        except (ValueError, TypeError):
                            pass
            elif role == "assistant":
                ai_message = data.get("ai_message") if isinstance(data, dict) else None
                if ai_message:
                    formatted_history.append({"role": "assistant", "content": ai_message})
                # 从 AI 响应中提取章节数量（可能在 conversation_state 中）
                if isinstance(data, dict):
                    conv_state = data.get("conversation_state", {})
                    if isinstance(conv_state, dict):
                        chapter_info = conv_state.get("chapter_count") or conv_state.get("total_chapters")
                        if chapter_info:
                            try:
                                total_chapters = int(chapter_info)
                            except (ValueError, TypeError):
                                pass
        except (json.JSONDecodeError, AttributeError):
            continue

    if not formatted_history:
        logger.warning("项目 %s 对话历史格式异常，无法提取有效内容", project_id)
        raise HTTPException(
            status_code=400,
            detail="无法从历史对话中提取有效内容，请检查对话历史格式或重新进行概念对话"
        )

    # 章节数量不做硬性限制，由用户在对话中决定
    total_chapters = max(10, total_chapters)  # 至少 10 章
    logger.info("项目 %s 计划生成 %d 章大纲", project_id, total_chapters)

    system_prompt = _ensure_prompt(await prompt_service.get_prompt("screenwriting"), "screenwriting")

    # 使用分段生成方法
    result = await llm_service.generate_blueprint_in_segments(
        system_prompt=system_prompt,
        conversation_history=formatted_history,
        total_chapters=total_chapters,
        user_id=current_user.id,
        chapters_per_batch=50,  # 每批生成 50 章
    )

    # 检查是否需要用户修复
    if not result.success:
        error = result.error
        logger.warning(
            "项目 %s 蓝图生成失败，需要用户修复: segment=%s error=%s",
            project_id,
            error.segment_name,
            error.error_message,
        )
        return BlueprintGenerationNeedsFixResponse(
            status="needs_fix",
            segment_name=error.segment_name,
            segment_index=error.segment_index,
            raw_response=error.raw_response,
            error_message=error.error_message,
            error_position=error.error_position,
            partial_blueprint=result.partial_blueprint or {},
            ai_message=(
                f"生成 {error.segment_name} 时遇到 JSON 格式错误：{error.error_message}\n\n"
                "请检查并修复下方的 JSON 内容，修复后点击继续生成。"
            ),
            generation_context=result.generation_context or {},
        )

    blueprint_data = result.blueprint

    # 转换 chapter_outline 格式（如果需要）
    if "chapter_outline" in blueprint_data:
        outlines = blueprint_data["chapter_outline"]
        # 确保每个章节都有正确的字段
        normalized_outlines = []
        for idx, outline in enumerate(outlines):
            normalized_outlines.append({
                "chapter_number": outline.get("chapter_number", idx + 1),
                "title": outline.get("title", f"第{idx + 1}章"),
                "summary": outline.get("summary", ""),
            })
        blueprint_data["chapter_outline"] = normalized_outlines

    blueprint = Blueprint(**blueprint_data)
    await novel_service.replace_blueprint(project_id, blueprint)
    if blueprint.title:
        project.title = blueprint.title
        project.status = "blueprint_ready"
        await session.commit()
        logger.info("项目 %s 更新标题为 %s，并标记为 blueprint_ready", project_id, blueprint.title)

    ai_message = (
        "太棒了！我已经根据我们的对话整理出完整的小说蓝图。请确认是否进入写作阶段，或提出修改意见。"
    )
    return BlueprintGenerationResponse(blueprint=blueprint, ai_message=ai_message)


@router.post("/{project_id}/blueprint/fix-and-continue")
async def fix_and_continue_blueprint(
    project_id: str,
    request: BlueprintFixAndContinueRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> BlueprintGenerationResponse | BlueprintGenerationNeedsFixResponse:
    """用户修复 JSON 后继续生成蓝图。

    接收用户修复后的 JSON 数据，合并到已有的部分蓝图中，然后继续生成剩余部分。
    """
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)
    logger.info(
        "项目 %s 用户修复 JSON 后继续生成: segment=%s",
        project_id,
        request.segment_name,
    )

    # 合并用户修复的数据到部分蓝图
    partial_blueprint = request.partial_blueprint.copy()
    partial_blueprint.update(request.fixed_data)

    # 获取生成上下文
    context = request.generation_context
    system_prompt = context.get("system_prompt", "")
    total_chapters = context.get("total_chapters", 20)
    chapters_per_batch = context.get("chapters_per_batch", 50)

    if not system_prompt:
        system_prompt = _ensure_prompt(await prompt_service.get_prompt("screenwriting"), "screenwriting")

    # 确定从哪个段继续生成
    segment_map = {
        "basic": 2,
        "world_setting": 3,
        "characters": 4,
        "relationships": 5,
        "chapter_outline": 5,  # chapter_outline 失败也从 5 开始
    }
    # 对于 chapter_outline_batch_N 格式
    segment_name = request.segment_name
    if segment_name.startswith("chapter_outline_batch_"):
        start_from_segment = 5
    else:
        start_from_segment = segment_map.get(segment_name, 1)

    # 获取原始对话历史
    history_records = await novel_service.list_conversations(project_id)
    formatted_history: List[Dict[str, str]] = []
    for record in history_records:
        role = record.role
        content = record.content
        if not role or not content:
            continue
        try:
            normalized = unwrap_markdown_json(content)
            data = json.loads(normalized)
            if role == "user":
                user_value = data.get("value", data)
                if isinstance(user_value, str):
                    formatted_history.append({"role": "user", "content": user_value})
            elif role == "assistant":
                ai_message = data.get("ai_message") if isinstance(data, dict) else None
                if ai_message:
                    formatted_history.append({"role": "assistant", "content": ai_message})
        except (json.JSONDecodeError, AttributeError):
            continue

    # 继续生成剩余部分
    result = await llm_service.generate_blueprint_in_segments(
        system_prompt=system_prompt,
        conversation_history=formatted_history,
        total_chapters=total_chapters,
        user_id=current_user.id,
        chapters_per_batch=chapters_per_batch,
        start_from_segment=start_from_segment,
        partial_blueprint=partial_blueprint,
    )

    # 检查是否还需要用户修复
    if not result.success:
        error = result.error
        logger.warning(
            "项目 %s 蓝图继续生成失败，仍需用户修复: segment=%s error=%s",
            project_id,
            error.segment_name,
            error.error_message,
        )
        return BlueprintGenerationNeedsFixResponse(
            status="needs_fix",
            segment_name=error.segment_name,
            segment_index=error.segment_index,
            raw_response=error.raw_response,
            error_message=error.error_message,
            error_position=error.error_position,
            partial_blueprint=result.partial_blueprint or {},
            ai_message=(
                f"生成 {error.segment_name} 时遇到 JSON 格式错误：{error.error_message}\n\n"
                "请检查并修复下方的 JSON 内容，修复后点击继续生成。"
            ),
            generation_context=result.generation_context or {},
        )

    blueprint_data = result.blueprint

    # 转换 chapter_outline 格式
    if "chapter_outline" in blueprint_data:
        outlines = blueprint_data["chapter_outline"]
        normalized_outlines = []
        for idx, outline in enumerate(outlines):
            normalized_outlines.append({
                "chapter_number": outline.get("chapter_number", idx + 1),
                "title": outline.get("title", f"第{idx + 1}章"),
                "summary": outline.get("summary", ""),
            })
        blueprint_data["chapter_outline"] = normalized_outlines

    blueprint = Blueprint(**blueprint_data)
    await novel_service.replace_blueprint(project_id, blueprint)
    if blueprint.title:
        project.title = blueprint.title
        project.status = "blueprint_ready"
        await session.commit()
        logger.info("项目 %s 修复后继续生成完成，标题为 %s", project_id, blueprint.title)

    ai_message = (
        "太棒了！我已经根据您的修复完成了小说蓝图的生成。请确认是否进入写作阶段，或提出修改意见。"
    )
    return BlueprintGenerationResponse(blueprint=blueprint, ai_message=ai_message)


@router.post("/{project_id}/blueprint/save", response_model=NovelProjectSchema)
async def save_blueprint(
    project_id: str,
    blueprint_data: Blueprint | None = Body(None),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """保存蓝图信息，可用于手动覆盖自动生成结果。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    if blueprint_data:
        await novel_service.replace_blueprint(project_id, blueprint_data)
        if blueprint_data.title:
            project.title = blueprint_data.title
            await session.commit()
        logger.info("项目 %s 手动保存蓝图", project_id)
    else:
        logger.warning("项目 %s 保存蓝图时未提供蓝图数据", project_id)
        raise HTTPException(status_code=400, detail="缺少蓝图数据，请提供有效的蓝图内容")

    return await novel_service.get_project_schema(project_id, current_user.id)


@router.patch("/{project_id}/blueprint", response_model=NovelProjectSchema)
async def patch_blueprint(
    project_id: str,
    payload: BlueprintPatch,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """局部更新蓝图字段，对世界观或角色做微调。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    await novel_service.patch_blueprint(project_id, update_data)
    logger.info("项目 %s 局部更新蓝图字段：%s", project_id, list(update_data.keys()))
    return await novel_service.get_project_schema(project_id, current_user.id)


# ===================================================================
# Part (篇) 管理端点
# ===================================================================


@router.post("/{project_id}/parts", response_model=PartSchema, status_code=status.HTTP_201_CREATED)
async def create_part(
    project_id: str,
    payload: PartCreate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> PartSchema:
    """创建新的篇(Part)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    part = await novel_service.create_part(project_id, payload.title, payload.description)
    logger.info("项目 %s 创建篇 %s (part_id=%s)", project_id, part.title, part.id)
    return PartSchema.model_validate(part)


@router.get("/{project_id}/parts", response_model=List[PartSchema])
async def list_parts(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> List[PartSchema]:
    """获取项目的所有篇(Parts)。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    logger.info("项目 %s 获取篇列表", project_id)
    return [PartSchema.model_validate(part) for part in sorted(project.parts, key=lambda p: p.position)]


@router.put("/{project_id}/parts/{part_id}", response_model=PartSchema)
async def update_part(
    project_id: str,
    part_id: int,
    payload: PartUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> PartSchema:
    """更新篇(Part)信息。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    part = await novel_service.update_part(part_id, **update_data)
    logger.info("项目 %s 更新篇 %s (part_id=%s)", project_id, part.title, part_id)
    return PartSchema.model_validate(part)


@router.delete("/{project_id}/parts/{part_id}", status_code=status.HTTP_200_OK)
async def delete_part(
    project_id: str,
    part_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """删除篇(Part)，级联删除所有关联的卷和章节。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.delete_part(part_id)
    logger.info("项目 %s 删除篇 part_id=%s", project_id, part_id)
    return {"status": "success", "message": f"成功删除篇 {part_id}"}


@router.post("/{project_id}/parts/reorder", status_code=status.HTTP_200_OK)
async def reorder_parts(
    project_id: str,
    payload: ReorderRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """重新排序所有篇(Parts)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.reorder_parts(project_id, payload.ids)
    logger.info("项目 %s 重排序篇，新顺序: %s", project_id, payload.ids)
    return {"status": "success", "message": "篇排序已更新"}


# ===================================================================
# Volume (卷) 管理端点
# ===================================================================


@router.post("/{project_id}/parts/{part_id}/volumes", response_model=VolumeSchema, status_code=status.HTTP_201_CREATED)
async def create_volume(
    project_id: str,
    part_id: int,
    payload: VolumeCreate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> VolumeSchema:
    """在指定篇(Part)下创建新的卷(Volume)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    volume = await novel_service.create_volume(part_id, payload.title, payload.description)
    logger.info("项目 %s 在篇 %s 下创建卷 %s (volume_id=%s)", project_id, part_id, volume.title, volume.id)
    return VolumeSchema.model_validate(volume)


@router.get("/{project_id}/volumes", response_model=List[VolumeSchema])
async def list_volumes(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> List[VolumeSchema]:
    """获取项目的所有卷(Volumes)。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    logger.info("项目 %s 获取卷列表", project_id)
    return [VolumeSchema.model_validate(volume) for volume in sorted(project.volumes, key=lambda v: v.position)]


@router.put("/{project_id}/volumes/{volume_id}", response_model=VolumeSchema)
async def update_volume(
    project_id: str,
    volume_id: int,
    payload: VolumeUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> VolumeSchema:
    """更新卷(Volume)信息。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    volume = await novel_service.update_volume(volume_id, **update_data)
    logger.info("项目 %s 更新卷 %s (volume_id=%s)", project_id, volume.title, volume_id)
    return VolumeSchema.model_validate(volume)


@router.delete("/{project_id}/volumes/{volume_id}", status_code=status.HTTP_200_OK)
async def delete_volume(
    project_id: str,
    volume_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """删除卷(Volume)，级联删除所有关联的章节。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.delete_volume(volume_id)
    logger.info("项目 %s 删除卷 volume_id=%s", project_id, volume_id)
    return {"status": "success", "message": f"成功删除卷 {volume_id}"}


@router.post("/{project_id}/volumes/{volume_id}/move", response_model=VolumeSchema)
async def move_volume_to_part(
    project_id: str,
    volume_id: int,
    payload: MoveVolumeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> VolumeSchema:
    """将卷(Volume)移动到其他篇(Part)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    volume = await novel_service.move_volume_to_part(volume_id, payload.target_part_id)
    logger.info("项目 %s 移动卷 %s 到篇 %s", project_id, volume_id, payload.target_part_id)
    return VolumeSchema.model_validate(volume)


@router.post("/{project_id}/parts/{part_id}/volumes/reorder", status_code=status.HTTP_200_OK)
async def reorder_volumes(
    project_id: str,
    part_id: int,
    payload: ReorderRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """重新排序指定篇下的所有卷(Volumes)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.reorder_volumes(part_id, payload.ids)
    logger.info("项目 %s 篇 %s 重排序卷，新顺序: %s", project_id, part_id, payload.ids)
    return {"status": "success", "message": "卷排序已更新"}


# ===================================================================
# 树形大纲与章节移动端点
# ===================================================================


@router.get("/{project_id}/outline-tree", response_model=OutlineTreeResponse)
async def get_outline_tree(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> OutlineTreeResponse:
    """获取项目的完整树形大纲结构（篇->卷->章）。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    tree_data = await novel_service.get_outline_tree(project_id)
    logger.info("项目 %s 获取树形大纲", project_id)
    return OutlineTreeResponse(**tree_data)


@router.post("/{project_id}/chapters/{chapter_outline_id}/move", response_model=ChapterSchema)
async def move_chapter_to_volume(
    project_id: str,
    chapter_outline_id: int,
    payload: MoveChapterRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ChapterSchema:
    """将章节移动到其他卷(Volume)。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    outline = await novel_service.move_chapter_to_volume(
        chapter_outline_id,
        payload.target_volume_id,
        payload.new_chapter_number
    )
    logger.info(
        "项目 %s 移动章节 %s 到卷 %s，新章节号 %s",
        project_id,
        chapter_outline_id,
        payload.target_volume_id,
        payload.new_chapter_number
    )

    # 返回完整的章节Schema
    return await novel_service.get_chapter_schema(project_id, current_user.id, payload.new_chapter_number)


# ===================================================================
# ChapterOutline (章节大纲) CRUD 端点
# ===================================================================


@router.post("/{project_id}/volumes/{volume_id}/chapters", response_model=ChapterOutlineDetail, status_code=status.HTTP_201_CREATED)
async def create_chapter_outline(
    project_id: str,
    volume_id: int,
    payload: ChapterOutlineCreate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ChapterOutlineDetail:
    """在指定卷下创建新的章节大纲。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    outline = await novel_service.create_chapter_outline(
        project_id,
        volume_id,
        payload.title,
        payload.summary
    )
    logger.info("项目 %s 在卷 %s 下创建章节 %s (outline_id=%s)", project_id, volume_id, outline.title, outline.id)
    return ChapterOutlineDetail.model_validate(outline)


@router.put("/{project_id}/chapters/outlines/{outline_id}", response_model=ChapterOutlineDetail)
async def update_chapter_outline(
    project_id: str,
    outline_id: int,
    payload: ChapterOutlineUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ChapterOutlineDetail:
    """更新章节大纲信息。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    outline = await novel_service.update_chapter_outline(outline_id, **update_data)
    logger.info("项目 %s 更新章节大纲 %s (outline_id=%s)", project_id, outline.title, outline_id)
    return ChapterOutlineDetail.model_validate(outline)


@router.delete("/{project_id}/chapters/outlines/{outline_id}", status_code=status.HTTP_200_OK)
async def delete_chapter_outline(
    project_id: str,
    outline_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """删除章节大纲。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.delete_chapter_outline(outline_id)
    logger.info("项目 %s 删除章节大纲 outline_id=%s", project_id, outline_id)
    return {"status": "success", "message": f"成功删除章节大纲 {outline_id}"}


# ===================================================================
# LLM 生成 Part/Volume 端点
# ===================================================================


@router.post("/{project_id}/parts/generate")
async def generate_parts(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """基于对话历史和蓝图信息生成篇章结构。"""
    novel_service = NovelService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)
    logger.info("项目 %s 开始生成 Part 大纲", project_id)

    # 获取对话历史
    history_records = await novel_service.list_conversations(project_id)
    if not history_records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少对话历史，请先完成概念对话"
        )

    # 格式化对话历史
    formatted_history: List[Dict[str, str]] = []
    for record in history_records:
        role = record.role
        content = record.content
        if not role or not content:
            continue
        try:
            normalized = unwrap_markdown_json(content)
            data = json.loads(normalized)
            if role == "user":
                user_value = data.get("value", data)
                if isinstance(user_value, str):
                    formatted_history.append({"role": "user", "content": user_value})
            elif role == "assistant":
                ai_message = data.get("ai_message") if isinstance(data, dict) else None
                if ai_message:
                    formatted_history.append({"role": "assistant", "content": ai_message})
        except (json.JSONDecodeError, AttributeError):
            continue

    if not formatted_history:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法从历史对话中提取有效内容"
        )

    # 获取蓝图基础信息
    blueprint = project.blueprint
    if not blueprint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目尚未生成蓝图，请先生成蓝图"
        )

    blueprint_info = {
        "title": blueprint.title or project.title,
        "genre": blueprint.genre or "",
        "style": blueprint.style or "",
        "tone": blueprint.tone or "",
        "full_synopsis": blueprint.full_synopsis or "",
        "estimated_length": "长篇",  # 可以根据 chapter_outline 数量动态计算
    }

    # 生成 Part 大纲
    result = await llm_service.generate_parts_outline(
        conversation_history=formatted_history,
        blueprint_info=blueprint_info,
        user_id=current_user.id,
    )

    logger.info("项目 %s 生成 Part 大纲完成，共 %d 个篇", project_id, len(result.get("parts", [])))

    return {
        "status": "success",
        "data": result,
        "ai_message": f"已为您生成 {len(result.get('parts', []))} 个篇的结构框架，请查看并确认。"
    }


@router.post("/{project_id}/parts/{part_id}/volumes/generate")
async def generate_volumes(
    project_id: str,
    part_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """为指定的篇生成卷结构。"""
    novel_service = NovelService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    # 获取指定的 Part
    part = await session.get(NovelPart, part_id)
    if not part or part.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="篇不存在或不属于该项目"
        )

    logger.info("项目 %s 篇 %s 开始生成 Volume 大纲", project_id, part.title)

    # 获取蓝图基础信息
    blueprint = project.blueprint
    if not blueprint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目尚未生成蓝图，请先生成蓝图"
        )

    blueprint_info = {
        "title": blueprint.title or project.title,
        "genre": blueprint.genre or "",
        "style": blueprint.style or "",
        "tone": blueprint.tone or "",
    }

    # 构建 Part 信息
    part_info = {
        "part_number": part.part_number,
        "title": part.title,
        "description": part.description or "",
        "estimated_chapters": 30,  # 可以根据实际情况计算
    }

    # 构建上下文（可选：获取前后篇的信息）
    # 手动查询所有 parts,避免懒加载
    from sqlalchemy import select
    stmt = select(NovelPart).where(NovelPart.project_id == project_id).order_by(NovelPart.position)
    result_parts = await session.execute(stmt)
    all_parts = list(result_parts.scalars().all())

    context = {}
    part_index = next((i for i, p in enumerate(all_parts) if p.id == part_id), None)

    if part_index is not None:
        if part_index > 0:
            prev_part = all_parts[part_index - 1]
            context["previous_part_summary"] = f"第{prev_part.part_number}篇: {prev_part.title} - {prev_part.description}"
        if part_index < len(all_parts) - 1:
            next_part = all_parts[part_index + 1]
            context["next_part_preview"] = f"第{next_part.part_number}篇: {next_part.title} - {next_part.description}"

    # 生成 Volume 大纲
    result = await llm_service.generate_volumes_outline(
        blueprint_info=blueprint_info,
        part_info=part_info,
        context=context,
        user_id=current_user.id,
    )

    logger.info(
        "项目 %s 篇 %s 生成 Volume 大纲完成，共 %d 个卷",
        project_id,
        part.title,
        len(result.get("volumes", []))
    )

    return {
        "status": "success",
        "data": result,
        "ai_message": f"已为篇《{part.title}》生成 {len(result.get('volumes', []))} 个卷的结构，请查看并确认。"
    }


# ===================================================================
# Character (角色) 管理端点
# ===================================================================


@router.put("/{project_id}/characters/{character_id}", response_model=CharacterDetail)
async def update_character(
    project_id: str,
    character_id: int,
    payload: CharacterUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> CharacterDetail:
    """更新角色信息"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    character = await novel_service.update_character(
        character_id,
        current_user.id,
        **update_data
    )
    logger.info("项目 %s 更新角色 %s (character_id=%s)", project_id, character.name, character_id)
    return CharacterDetail.model_validate(character)


@router.post("/{project_id}/characters/{character_id}/image", status_code=status.HTTP_200_OK)
async def upload_character_image(
    project_id: str,
    character_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """上传角色图片"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    # 读取文件内容
    file_content = await file.read()

    try:
        image_path = await novel_service.upload_character_image(
            character_id,
            current_user.id,
            file_content,
            file.filename or "image.jpg",
            file.content_type or "image/jpeg"
        )
        logger.info("项目 %s 角色 %s 上传图片成功", project_id, character_id)
        return {"status": "success", "image_path": image_path}
    except ValueError as e:
        logger.warning("项目 %s 角色 %s 上传图片失败: %s", project_id, character_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{project_id}/characters/{character_id}/image", status_code=status.HTTP_200_OK)
async def delete_character_image(
    project_id: str,
    character_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """删除角色图片"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    await novel_service.delete_character_image(character_id, current_user.id)
    logger.info("项目 %s 角色 %s 删除图片", project_id, character_id)
    return {"status": "success", "message": "图片已删除"}


@router.get("/{project_id}/characters/groups", response_model=CharacterGroupsResponse)
async def get_character_groups(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> CharacterGroupsResponse:
    """获取项目中所有使用的角色分组"""
    novel_service = NovelService(session)
    groups = await novel_service.get_character_groups(project_id, current_user.id)
    logger.info("项目 %s 获取角色分组列表，共 %d 个", project_id, len(groups))
    return CharacterGroupsResponse(groups=groups)


@router.post("/{project_id}/characters/groups/rename", status_code=status.HTTP_200_OK)
async def rename_character_group(
    project_id: str,
    old_group: str = Body(...),
    new_group: str = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """重命名角色分组"""
    novel_service = NovelService(session)

    count = await novel_service.batch_update_character_group(
        project_id,
        current_user.id,
        old_group,
        new_group
    )
    logger.info("项目 %s 重命名分组 '%s' -> '%s'，影响 %d 个角色", project_id, old_group, new_group, count)
    return {"status": "success", "message": f"已更新 {count} 个角色的分组", "affected_count": count}

