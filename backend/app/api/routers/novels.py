import json
import logging
from typing import Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.dependencies import get_current_user
from ...db.session import get_session
from ...schemas.novel import (
    Blueprint,
    BlueprintFixAndContinueRequest,
    BlueprintGenerationNeedsFixResponse,
    BlueprintGenerationResponse,
    BlueprintPatch,
    Chapter as ChapterSchema,
    ConverseRequest,
    ConverseResponse,
    NovelProject as NovelProjectSchema,
    NovelProjectSummary,
    NovelSectionResponse,
    NovelSectionType,
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
