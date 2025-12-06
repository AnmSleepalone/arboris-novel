from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

_PREFERRED_CONTENT_KEYS: tuple[str, ...] = (
    "content",
    "chapter_content",
    "chapter_text",
    "full_content",
    "text",
    "body",
    "story",
    "chapter",
    "real_summary",
    "summary",
)


def _normalize_version_content(raw_content: Any, metadata: Any) -> str:
    text = _coerce_text(metadata)
    if not text:
        text = _coerce_text(raw_content)
    return text or ""


def _coerce_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_string(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in _PREFERRED_CONTENT_KEYS:
            if key in value and value[key]:
                nested = _coerce_text(value[key])
                if nested:
                    return nested
        return _clean_string(json.dumps(value, ensure_ascii=False))
    if isinstance(value, (list, tuple, set)):
        parts = [text for text in (_coerce_text(item) for item in value) if text]
        if parts:
            return "\n".join(parts)
        return None
    return _clean_string(str(value))


def _clean_string(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            coerced = _coerce_text(parsed)
            if coerced:
                return coerced
        except json.JSONDecodeError:
            pass
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        stripped = stripped[1:-1]
    return (
        stripped.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    BlueprintCharacter,
    BlueprintRelationship,
    Chapter,
    ChapterEvaluation,
    ChapterOutline,
    ChapterVersion,
    NovelBlueprint,
    NovelConversation,
    NovelPart,
    NovelProject,
    NovelVolume,
)
from ..repositories.novel_repository import NovelRepository
from ..schemas.admin import AdminNovelSummary
from ..schemas.novel import (
    Blueprint,
    Chapter as ChapterSchema,
    ChapterGenerationStatus,
    ChapterOutline as ChapterOutlineSchema,
    NovelProject as NovelProjectSchema,
    NovelProjectSummary,
    NovelSectionResponse,
    NovelSectionType,
)


class NovelService:
    """小说项目服务，基于拆表后的结构提供聚合与业务操作。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = NovelRepository(session)

    # ------------------------------------------------------------------
    # 项目与摘要
    # ------------------------------------------------------------------
    async def create_project(self, user_id: int, title: str, initial_prompt: str) -> NovelProject:
        project = NovelProject(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            initial_prompt=initial_prompt,
        )
        blueprint = NovelBlueprint(project=project)
        self.session.add_all([project, blueprint])
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def ensure_project_owner(self, project_id: str, user_id: int) -> NovelProject:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        if project.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该项目")
        return project

    async def get_project_schema(self, project_id: str, user_id: int) -> NovelProjectSchema:
        project = await self.ensure_project_owner(project_id, user_id)
        return await self._serialize_project(project)

    async def get_section_data(
        self,
        project_id: str,
        user_id: int,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        project = await self.ensure_project_owner(project_id, user_id)
        return self._build_section_response(project, section)

    async def get_chapter_schema(
        self,
        project_id: str,
        user_id: int,
        chapter_number: int,
    ) -> ChapterSchema:
        project = await self.ensure_project_owner(project_id, user_id)
        return self._build_chapter_schema(project, chapter_number)

    async def list_projects_for_user(self, user_id: int) -> List[NovelProjectSummary]:
        projects = await self.repo.list_by_user(user_id)
        summaries: List[NovelProjectSummary] = []
        for project in projects:
            blueprint = project.blueprint
            genre = blueprint.genre if blueprint and blueprint.genre else "未知"
            outlines = project.outlines
            chapters = project.chapters
            total = len(outlines) or len(chapters)
            completed = sum(1 for chapter in chapters if chapter.selected_version_id)
            summaries.append(
                NovelProjectSummary(
                    id=project.id,
                    title=project.title,
                    genre=genre,
                    last_edited=project.updated_at.isoformat() if project.updated_at else "未知",
                    completed_chapters=completed,
                    total_chapters=total,
                )
            )
        return summaries

    async def list_projects_for_admin(self) -> List[AdminNovelSummary]:
        projects = await self.repo.list_all()
        summaries: List[AdminNovelSummary] = []
        for project in projects:
            blueprint = project.blueprint
            genre = blueprint.genre if blueprint and blueprint.genre else "未知"
            outlines = project.outlines
            chapters = project.chapters
            total = len(outlines) or len(chapters)
            completed = sum(1 for chapter in chapters if chapter.selected_version_id)
            owner = project.owner
            summaries.append(
                AdminNovelSummary(
                    id=project.id,
                    title=project.title,
                    owner_id=owner.id if owner else 0,
                    owner_username=owner.username if owner else "未知",
                    genre=genre,
                    last_edited=project.updated_at.isoformat() if project.updated_at else "",
                    completed_chapters=completed,
                    total_chapters=total,
                )
            )
        return summaries

    async def delete_projects(self, project_ids: List[str], user_id: int) -> None:
        for pid in project_ids:
            project = await self.ensure_project_owner(pid, user_id)
            await self.repo.delete(project)
        await self.session.commit()

    async def count_projects(self) -> int:
        result = await self.session.execute(select(func.count(NovelProject.id)))
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 对话管理
    # ------------------------------------------------------------------
    async def list_conversations(self, project_id: str) -> List[NovelConversation]:
        stmt = (
            select(NovelConversation)
            .where(NovelConversation.project_id == project_id)
            .order_by(NovelConversation.seq.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def append_conversation(self, project_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        result = await self.session.execute(
            select(func.max(NovelConversation.seq)).where(NovelConversation.project_id == project_id)
        )
        current_max = result.scalar()
        next_seq = (current_max or 0) + 1
        convo = NovelConversation(
            project_id=project_id,
            seq=next_seq,
            role=role,
            content=content,
            metadata=metadata,
        )
        self.session.add(convo)
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 蓝图管理
    # ------------------------------------------------------------------
    async def replace_blueprint(self, project_id: str, blueprint: Blueprint) -> None:
        record = await self.session.get(NovelBlueprint, project_id)
        if not record:
            record = NovelBlueprint(project_id=project_id)
            self.session.add(record)
        record.title = blueprint.title
        record.target_audience = blueprint.target_audience
        record.genre = blueprint.genre
        record.style = blueprint.style
        record.tone = blueprint.tone
        record.one_sentence_summary = blueprint.one_sentence_summary
        record.full_synopsis = blueprint.full_synopsis
        record.world_setting = blueprint.world_setting

        await self.session.execute(delete(BlueprintCharacter).where(BlueprintCharacter.project_id == project_id))
        for index, data in enumerate(blueprint.characters):
            self.session.add(
                BlueprintCharacter(
                    project_id=project_id,
                    name=data.get("name", ""),
                    identity=data.get("identity"),
                    personality=data.get("personality"),
                    goals=data.get("goals"),
                    abilities=data.get("abilities"),
                    relationship_to_protagonist=data.get("relationship_to_protagonist"),
                    extra={k: v for k, v in data.items() if k not in {
                        "name",
                        "identity",
                        "personality",
                        "goals",
                        "abilities",
                        "relationship_to_protagonist",
                    }},
                    position=index,
                )
            )

        await self.session.execute(delete(BlueprintRelationship).where(BlueprintRelationship.project_id == project_id))
        for index, relation in enumerate(blueprint.relationships):
            self.session.add(
                BlueprintRelationship(
                    project_id=project_id,
                    character_from=relation.character_from,
                    character_to=relation.character_to,
                    description=relation.description,
                    position=index,
                )
            )

        await self.session.execute(delete(ChapterOutline).where(ChapterOutline.project_id == project_id))
        for outline in blueprint.chapter_outline:
            self.session.add(
                ChapterOutline(
                    project_id=project_id,
                    chapter_number=outline.chapter_number,
                    title=outline.title,
                    summary=outline.summary,
                )
            )

        await self.session.commit()
        await self._touch_project(project_id)

    async def patch_blueprint(self, project_id: str, patch: Dict) -> None:
        blueprint = await self.session.get(NovelBlueprint, project_id)
        if not blueprint:
            blueprint = NovelBlueprint(project_id=project_id)
            self.session.add(blueprint)

        if "one_sentence_summary" in patch:
            blueprint.one_sentence_summary = patch["one_sentence_summary"]
        if "full_synopsis" in patch:
            blueprint.full_synopsis = patch["full_synopsis"]
        if "world_setting" in patch and patch["world_setting"] is not None:
            # 创建新字典对象以触发 SQLAlchemy 的变更检测
            existing = blueprint.world_setting or {}
            blueprint.world_setting = {**existing, **patch["world_setting"]}
        if "characters" in patch and patch["characters"] is not None:
            await self.session.execute(delete(BlueprintCharacter).where(BlueprintCharacter.project_id == project_id))
            for index, data in enumerate(patch["characters"]):
                self.session.add(
                    BlueprintCharacter(
                        project_id=project_id,
                        name=data.get("name", ""),
                        identity=data.get("identity"),
                        personality=data.get("personality"),
                        goals=data.get("goals"),
                        abilities=data.get("abilities"),
                        relationship_to_protagonist=data.get("relationship_to_protagonist"),
                        extra={k: v for k, v in data.items() if k not in {
                            "name",
                            "identity",
                            "personality",
                            "goals",
                            "abilities",
                            "relationship_to_protagonist",
                        }},
                        position=index,
                    )
                )
        if "relationships" in patch and patch["relationships"] is not None:
            await self.session.execute(delete(BlueprintRelationship).where(BlueprintRelationship.project_id == project_id))
            for index, relation in enumerate(patch["relationships"]):
                self.session.add(
                    BlueprintRelationship(
                        project_id=project_id,
                        character_from=relation.get("character_from"),
                        character_to=relation.get("character_to"),
                        description=relation.get("description"),
                        position=index,
                    )
                )
        if "chapter_outline" in patch and patch["chapter_outline"] is not None:
            await self.session.execute(delete(ChapterOutline).where(ChapterOutline.project_id == project_id))
            for outline in patch["chapter_outline"]:
                self.session.add(
                    ChapterOutline(
                        project_id=project_id,
                        chapter_number=outline.get("chapter_number"),
                        title=outline.get("title", ""),
                        summary=outline.get("summary"),
                    )
                )
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 章节与版本
    # ------------------------------------------------------------------
    async def get_outline(self, project_id: str, chapter_number: int) -> Optional[ChapterOutline]:
        stmt = (
            select(ChapterOutline)
            .where(
                ChapterOutline.project_id == project_id,
                ChapterOutline.chapter_number == chapter_number,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_or_create_chapter(self, project_id: str, chapter_number: int) -> Chapter:
        stmt = (
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.chapter_number == chapter_number,
            )
        )
        result = await self.session.execute(stmt)
        chapter = result.scalars().first()
        if chapter:
            return chapter
        chapter = Chapter(project_id=project_id, chapter_number=chapter_number)
        self.session.add(chapter)
        await self.session.commit()
        await self.session.refresh(chapter)
        return chapter

    async def replace_chapter_versions(self, chapter: Chapter, contents: List[str], metadata: Optional[List[Dict]] = None) -> List[ChapterVersion]:
        await self.session.execute(delete(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id))
        versions: List[ChapterVersion] = []
        for index, content in enumerate(contents):
            extra = metadata[index] if metadata and index < len(metadata) else None
            text_content = _normalize_version_content(content, extra)
            version = ChapterVersion(
                chapter_id=chapter.id,
                content=text_content,
                metadata=None,
                version_label=f"v{index+1}",
            )
            self.session.add(version)
            versions.append(version)
        chapter.status = ChapterGenerationStatus.WAITING_FOR_CONFIRM.value
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)
        return versions

    async def select_chapter_version(self, chapter: Chapter, version_index: int) -> ChapterVersion:
        versions = sorted(chapter.versions, key=lambda item: item.created_at)
        if not versions or version_index < 0 or version_index >= len(versions):
            raise HTTPException(status_code=400, detail="版本索引无效")
        selected = versions[version_index]
        chapter.selected_version_id = selected.id
        chapter.status = ChapterGenerationStatus.SUCCESSFUL.value
        chapter.word_count = len(selected.content or "")
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)
        return selected

    async def add_chapter_evaluation(self, chapter: Chapter, version: Optional[ChapterVersion], feedback: str, decision: Optional[str] = None) -> None:
        evaluation = ChapterEvaluation(
            chapter_id=chapter.id,
            version_id=version.id if version else None,
            feedback=feedback,
            decision=decision,
        )
        self.session.add(evaluation)
        chapter.status = ChapterGenerationStatus.WAITING_FOR_CONFIRM.value
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)

    async def delete_chapters(self, project_id: str, chapter_numbers: Iterable[int]) -> None:
        await self.session.execute(
            delete(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.chapter_number.in_(list(chapter_numbers)),
            )
        )
        await self.session.execute(
            delete(ChapterOutline).where(
                ChapterOutline.project_id == project_id,
                ChapterOutline.chapter_number.in_(list(chapter_numbers)),
            )
        )
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 序列化辅助
    # ------------------------------------------------------------------
    async def get_project_schema_for_admin(self, project_id: str) -> NovelProjectSchema:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return await self._serialize_project(project)

    async def get_section_data_for_admin(
        self,
        project_id: str,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return self._build_section_response(project, section)

    async def get_chapter_schema_for_admin(
        self,
        project_id: str,
        chapter_number: int,
    ) -> ChapterSchema:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return self._build_chapter_schema(project, chapter_number)

    async def _serialize_project(self, project: NovelProject) -> NovelProjectSchema:
        conversations = [
            {"role": convo.role, "content": convo.content}
            for convo in sorted(project.conversations, key=lambda c: c.seq)
        ]

        blueprint_schema = self._build_blueprint_schema(project)

        outlines_map = {outline.chapter_number: outline for outline in project.outlines}
        chapters_map = {chapter.chapter_number: chapter for chapter in project.chapters}
        chapter_numbers = sorted(set(outlines_map.keys()) | set(chapters_map.keys()))
        chapters_schema: List[ChapterSchema] = [
            self._build_chapter_schema(
                project,
                number,
                outlines_map=outlines_map,
                chapters_map=chapters_map,
            )
            for number in chapter_numbers
        ]

        return NovelProjectSchema(
            id=project.id,
            user_id=project.user_id,
            title=project.title,
            initial_prompt=project.initial_prompt or "",
            conversation_history=conversations,
            blueprint=blueprint_schema,
            chapters=chapters_schema,
        )

    async def _touch_project(self, project_id: str) -> None:
        await self.session.execute(
            update(NovelProject)
            .where(NovelProject.id == project_id)
            .values(updated_at=datetime.now(timezone.utc))
        )
        await self.session.commit()

    def _build_blueprint_schema(self, project: NovelProject) -> Blueprint:
        blueprint_obj = project.blueprint
        if blueprint_obj:
            return Blueprint(
                title=blueprint_obj.title or "",
                target_audience=blueprint_obj.target_audience or "",
                genre=blueprint_obj.genre or "",
                style=blueprint_obj.style or "",
                tone=blueprint_obj.tone or "",
                one_sentence_summary=blueprint_obj.one_sentence_summary or "",
                full_synopsis=blueprint_obj.full_synopsis or "",
                world_setting=blueprint_obj.world_setting or {},
                characters=[
                    {
                        "id": character.id,
                        "name": character.name,
                        "identity": character.identity,
                        "personality": character.personality,
                        "goals": character.goals,
                        "abilities": character.abilities,
                        "relationship_to_protagonist": character.relationship_to_protagonist,
                        "image_path": character.image_path,
                        "group_type": character.group_type,
                        "appearance_period": character.appearance_period,
                        **(character.extra or {}),
                    }
                    for character in sorted(project.characters, key=lambda c: c.position)
                ],
                relationships=[
                    {
                        "character_from": relation.character_from,
                        "character_to": relation.character_to,
                        "description": relation.description or "",
                        "relationship_type": getattr(relation, "relationship_type", None),
                    }
                    for relation in sorted(project.relationships_, key=lambda r: r.position)
                ],
                chapter_outline=[
                    ChapterOutlineSchema(
                        chapter_number=outline.chapter_number,
                        title=outline.title,
                        summary=outline.summary or "",
                    )
                    for outline in sorted(project.outlines, key=lambda o: o.chapter_number)
                ],
            )
        return Blueprint(
            title="",
            target_audience="",
            genre="",
            style="",
            tone="",
            one_sentence_summary="",
            full_synopsis="",
            world_setting={},
            characters=[],
            relationships=[],
            chapter_outline=[],
        )

    def _build_section_response(
        self,
        project: NovelProject,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        blueprint = self._build_blueprint_schema(project)

        if section == NovelSectionType.OVERVIEW:
            data = {
                "title": project.title,
                "initial_prompt": project.initial_prompt or "",
                "status": project.status,
                "one_sentence_summary": blueprint.one_sentence_summary,
                "target_audience": blueprint.target_audience,
                "genre": blueprint.genre,
                "style": blueprint.style,
                "tone": blueprint.tone,
                "full_synopsis": blueprint.full_synopsis,
                "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            }
        elif section == NovelSectionType.WORLD_SETTING:
            data = {
                "world_setting": blueprint.world_setting or {},
            }
        elif section == NovelSectionType.CHARACTERS:
            data = {
                "characters": blueprint.characters,
            }
        elif section == NovelSectionType.RELATIONSHIPS:
            data = {
                "relationships": blueprint.relationships,
            }
        elif section == NovelSectionType.CHAPTER_OUTLINE:
            data = {
                "chapter_outline": [outline.model_dump() for outline in blueprint.chapter_outline],
            }
        elif section == NovelSectionType.CHAPTERS:
            outlines_map = {outline.chapter_number: outline for outline in project.outlines}
            chapters_map = {chapter.chapter_number: chapter for chapter in project.chapters}
            chapter_numbers = sorted(set(outlines_map.keys()) | set(chapters_map.keys()))
            # 章节列表只返回元数据，不包含完整内容
            chapters = [
                self._build_chapter_schema(
                    project,
                    number,
                    outlines_map=outlines_map,
                    chapters_map=chapters_map,
                    include_content=False,
                ).model_dump()
                for number in chapter_numbers
            ]
            data = {
                "chapters": chapters,
                "total": len(chapters),
            }
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的章节类型")

        return NovelSectionResponse(section=section, data=data)

    def _build_chapter_schema(
        self,
        project: NovelProject,
        chapter_number: int,
        *,
        outlines_map: Optional[Dict[int, ChapterOutline]] = None,
        chapters_map: Optional[Dict[int, Chapter]] = None,
        include_content: bool = True,
    ) -> ChapterSchema:
        outlines = outlines_map or {outline.chapter_number: outline for outline in project.outlines}
        chapters = chapters_map or {chapter.chapter_number: chapter for chapter in project.chapters}
        outline = outlines.get(chapter_number)
        chapter = chapters.get(chapter_number)

        if not outline and not chapter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")

        title = outline.title if outline else f"第{chapter_number}章"
        summary = outline.summary if outline and outline.summary else None
        real_summary = chapter.real_summary if chapter else None
        content = None
        versions: Optional[List[str]] = None
        evaluation_text: Optional[str] = None
        status_value = ChapterGenerationStatus.NOT_GENERATED.value
        word_count = 0

        if chapter:
            status_value = chapter.status or ChapterGenerationStatus.NOT_GENERATED.value
            word_count = chapter.word_count or 0

            # 只有在 include_content=True 时才包含完整内容
            if include_content:
                if chapter.selected_version:
                    content = chapter.selected_version.content
                if chapter.versions:
                    versions = [
                        v.content
                        for v in sorted(chapter.versions, key=lambda item: item.created_at)
                    ]
                if chapter.evaluations:
                    latest = sorted(chapter.evaluations, key=lambda item: item.created_at)[-1]
                    evaluation_text = latest.feedback or latest.decision

        return ChapterSchema(
            chapter_number=chapter_number,
            title=title,
            summary=summary,
            real_summary=real_summary,
            content=content,
            versions=versions,
            evaluation=evaluation_text,
            generation_status=ChapterGenerationStatus(status_value),
            word_count=word_count,
        )

    # ------------------------------------------------------------------
    # Part 管理
    # ------------------------------------------------------------------
    async def create_part(self, project_id: str, title: str, description: str = None) -> NovelPart:
        """创建新的Part"""
        stmt = select(
            func.max(NovelPart.part_number),
            func.max(NovelPart.position)
        ).where(NovelPart.project_id == project_id)
        result = await self.session.execute(stmt)
        max_number, max_position = result.one()

        part = NovelPart(
            project_id=project_id,
            part_number=(max_number or 0) + 1,
            title=title,
            description=description,
            position=(max_position or 0) + 100
        )
        self.session.add(part)
        await self.session.commit()
        await self.session.refresh(part)
        return part

    async def update_part(self, part_id: int, title: str = None, description: str = None) -> NovelPart:
        """更新Part信息"""
        part = await self.session.get(NovelPart, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part不存在")

        if title is not None:
            part.title = title
        if description is not None:
            part.description = description

        await self.session.commit()
        await self.session.refresh(part)
        return part

    async def delete_part(self, part_id: int) -> None:
        """删除Part(级联删除所有Volume和Chapter)"""
        part = await self.session.get(NovelPart, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part不存在")

        await self.session.delete(part)
        await self.session.commit()

    async def reorder_parts(self, project_id: str, part_ids: List[int]) -> None:
        """重新排序Parts"""
        for idx, part_id in enumerate(part_ids):
            stmt = update(NovelPart).where(NovelPart.id == part_id).values(position=idx * 100)
            await self.session.execute(stmt)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Volume 管理
    # ------------------------------------------------------------------
    async def create_volume(self, part_id: int, title: str, description: str = None) -> NovelVolume:
        """创建新的Volume"""
        part = await self.session.get(NovelPart, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part不存在")

        stmt = select(
            func.max(NovelVolume.volume_number),
            func.max(NovelVolume.position)
        ).where(NovelVolume.part_id == part_id)
        result = await self.session.execute(stmt)
        max_number, max_position = result.one()

        volume = NovelVolume(
            project_id=part.project_id,
            part_id=part_id,
            volume_number=(max_number or 0) + 1,
            title=title,
            description=description,
            position=(max_position or 0) + 100
        )
        self.session.add(volume)
        await self.session.commit()
        await self.session.refresh(volume)
        return volume

    async def update_volume(self, volume_id: int, title: str = None, description: str = None) -> NovelVolume:
        """更新Volume信息"""
        volume = await self.session.get(NovelVolume, volume_id)
        if not volume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume不存在")

        if title is not None:
            volume.title = title
        if description is not None:
            volume.description = description

        await self.session.commit()
        await self.session.refresh(volume)
        return volume

    async def delete_volume(self, volume_id: int) -> None:
        """删除Volume(级联删除所有Chapter)"""
        volume = await self.session.get(NovelVolume, volume_id)
        if not volume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume不存在")

        await self.session.delete(volume)
        await self.session.commit()

    async def move_volume_to_part(self, volume_id: int, target_part_id: int) -> NovelVolume:
        """将Volume移动到其他Part"""
        volume = await self.session.get(NovelVolume, volume_id)
        target_part = await self.session.get(NovelPart, target_part_id)

        if not volume or not target_part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume或Part不存在")

        if volume.project_id != target_part.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能跨项目移动")

        # 获取目标Part的最大volume_number
        stmt = select(func.max(NovelVolume.volume_number)).where(
            NovelVolume.part_id == target_part_id
        )
        max_number = (await self.session.execute(stmt)).scalar_one()

        volume.part_id = target_part_id
        volume.volume_number = (max_number or 0) + 1

        await self.session.commit()
        await self.session.refresh(volume)
        return volume

    async def reorder_volumes(self, part_id: int, volume_ids: List[int]) -> None:
        """重新排序Volumes"""
        for idx, volume_id in enumerate(volume_ids):
            stmt = update(NovelVolume).where(NovelVolume.id == volume_id).values(position=idx * 100)
            await self.session.execute(stmt)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Chapter 增强操作
    # ------------------------------------------------------------------
    async def move_chapter_to_volume(
        self,
        chapter_outline_id: int,
        target_volume_id: int,
        new_chapter_number: int
    ) -> ChapterOutline:
        """将Chapter移动到其他Volume"""
        outline = await self.session.get(ChapterOutline, chapter_outline_id)
        target_volume = await self.session.get(NovelVolume, target_volume_id)

        if not outline or not target_volume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter或Volume不存在")

        if outline.project_id != target_volume.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能跨项目移动")

        old_volume_id = outline.volume_id
        old_chapter_number = outline.chapter_number

        # 如果位置没变,直接返回
        if old_volume_id == target_volume_id and old_chapter_number == new_chapter_number:
            return outline

        # 新策略: 使用大偏移量避免冲突
        # 1. 先给所有相关章节加上大偏移量 (10000)
        # 2. 然后重新分配最终的章节号
        # 3. 这样可以完全避免中间状态的冲突

        OFFSET = 10000

        if old_volume_id == target_volume_id:
            # 同卷内移动
            # 步骤1: 所有章节加上大偏移量
            stmt = update(ChapterOutline).where(
                ChapterOutline.volume_id == target_volume_id
            ).values(chapter_number=ChapterOutline.chapter_number + OFFSET)
            await self.session.execute(stmt)
            await self.session.flush()

            # 步骤2: 查询所有章节并重新排序
            stmt = select(ChapterOutline).where(
                ChapterOutline.volume_id == target_volume_id
            ).order_by(ChapterOutline.chapter_number)
            result = await self.session.execute(stmt)
            all_chapters = list(result.scalars().all())

            # 步骤3: 构建新的顺序
            # 找到当前章节在列表中的位置
            current_index = next((i for i, ch in enumerate(all_chapters) if ch.id == chapter_outline_id), None)
            if current_index is None:
                raise ValueError("找不到当前章节")

            # 移除当前章节
            moving_chapter = all_chapters.pop(current_index)

            # 插入到新位置 (new_chapter_number - 1 因为是0-based索引)
            insert_index = new_chapter_number - 1
            all_chapters.insert(insert_index, moving_chapter)

            # 步骤4: 重新分配章节号
            for idx, chapter in enumerate(all_chapters, start=1):
                chapter.chapter_number = idx

            await self.session.flush()

        else:
            # 跨卷移动
            # 步骤1: 给两个卷的所有章节都加上大偏移量
            stmt = update(ChapterOutline).where(
                ChapterOutline.volume_id.in_([old_volume_id, target_volume_id])
            ).values(chapter_number=ChapterOutline.chapter_number + OFFSET)
            await self.session.execute(stmt)
            await self.session.flush()

            # 步骤2: 查询两个卷的所有章节
            stmt = select(ChapterOutline).where(
                ChapterOutline.volume_id == old_volume_id
            ).order_by(ChapterOutline.chapter_number)
            result = await self.session.execute(stmt)
            old_volume_chapters = list(result.scalars().all())

            stmt = select(ChapterOutline).where(
                ChapterOutline.volume_id == target_volume_id
            ).order_by(ChapterOutline.chapter_number)
            result = await self.session.execute(stmt)
            target_volume_chapters = list(result.scalars().all())

            # 步骤3: 从旧卷移除当前章节
            current_index = next((i for i, ch in enumerate(old_volume_chapters) if ch.id == chapter_outline_id), None)
            if current_index is None:
                raise ValueError("找不到当前章节")

            moving_chapter = old_volume_chapters.pop(current_index)

            # 步骤4: 插入到新卷
            insert_index = new_chapter_number - 1
            target_volume_chapters.insert(insert_index, moving_chapter)

            # 步骤5: 重新分配旧卷的章节号
            for idx, chapter in enumerate(old_volume_chapters, start=1):
                chapter.chapter_number = idx

            # 步骤6: 重新分配新卷的章节号,并更新volume_id
            for idx, chapter in enumerate(target_volume_chapters, start=1):
                chapter.volume_id = target_volume_id
                chapter.chapter_number = idx

            await self.session.flush()

        # 更新 outline 的引用 (已经在上面更新了,这里再确认一次)
        await self.session.refresh(outline)

        # 同步更新 chapters 表
        stmt = update(Chapter).where(
            Chapter.volume_id == old_volume_id,
            Chapter.chapter_number == old_chapter_number
        ).values(
            volume_id=target_volume_id,
            chapter_number=new_chapter_number
        )
        await self.session.execute(stmt)

        await self.session.commit()
        await self.session.refresh(outline)
        return outline

    # ------------------------------------------------------------------
    # 树形查询
    # ------------------------------------------------------------------
    async def get_outline_tree(self, project_id: str) -> Dict[str, Any]:
        """获取完整的树形大纲结构"""
        stmt = (
            select(NovelPart)
            .where(NovelPart.project_id == project_id)
            .options(
                selectinload(NovelPart.volumes).selectinload(NovelVolume.outlines)
            )
            .order_by(NovelPart.position)
        )
        result = await self.session.execute(stmt)
        parts = result.scalars().all()

        return {
            "parts": [
                {
                    "id": part.id,
                    "project_id": part.project_id,
                    "part_number": part.part_number,
                    "title": part.title,
                    "description": part.description,
                    "position": part.position,
                    "volumes": [
                        {
                            "id": volume.id,
                            "project_id": volume.project_id,
                            "part_id": volume.part_id,
                            "volume_number": volume.volume_number,
                            "title": volume.title,
                            "description": volume.description,
                            "position": volume.position,
                            "chapters": [
                                {
                                    "id": outline.id,
                                    "volume_id": outline.volume_id,
                                    "chapter_number": outline.chapter_number,
                                    "title": outline.title,
                                    "summary": outline.summary
                                }
                                for outline in sorted(
                                    volume.outlines,
                                    key=lambda o: o.chapter_number
                                )
                            ]
                        }
                        for volume in sorted(part.volumes, key=lambda v: v.position)
                    ]
                }
                for part in parts
            ]
        }

    # ------------------------------------------------------------------
    # ChapterOutline (章节大纲) 管理
    # ------------------------------------------------------------------

    async def create_chapter_outline(
        self,
        project_id: str,
        volume_id: int,
        title: str,
        summary: Optional[str] = None,
    ) -> ChapterOutline:
        """创建新的章节大纲"""
        # 获取该卷中的最大章节号
        stmt = (
            select(func.max(ChapterOutline.chapter_number))
            .where(ChapterOutline.volume_id == volume_id)
        )
        result = await self.session.execute(stmt)
        max_chapter_number = result.scalar()
        next_chapter_number = (max_chapter_number or 0) + 1

        outline = ChapterOutline(
            project_id=project_id,
            volume_id=volume_id,
            chapter_number=next_chapter_number,
            title=title,
            summary=summary,
        )
        self.session.add(outline)
        await self.session.commit()
        await self.session.refresh(outline)
        return outline

    async def update_chapter_outline(
        self,
        outline_id: int,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> ChapterOutline:
        """更新章节大纲"""
        stmt = select(ChapterOutline).where(ChapterOutline.id == outline_id)
        result = await self.session.execute(stmt)
        outline = result.scalar_one_or_none()
        if not outline:
            raise ValueError(f"章节大纲 {outline_id} 不存在")

        if title is not None:
            outline.title = title
        if summary is not None:
            outline.summary = summary

        await self.session.commit()
        await self.session.refresh(outline)
        return outline

    async def delete_chapter_outline(self, outline_id: int) -> None:
        """删除章节大纲"""
        stmt = select(ChapterOutline).where(ChapterOutline.id == outline_id)
        result = await self.session.execute(stmt)
        outline = result.scalar_one_or_none()
        if not outline:
            raise ValueError(f"章节大纲 {outline_id} 不存在")

        await self.session.delete(outline)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Character 相关方法
    # ------------------------------------------------------------------

    async def get_character(self, character_id: int, user_id: int) -> BlueprintCharacter:
        """获取角色详情"""
        from ..models import BlueprintCharacter
        stmt = select(BlueprintCharacter).where(BlueprintCharacter.id == character_id)
        result = await self.session.execute(stmt)
        character = result.scalar_one_or_none()

        if not character:
            raise ValueError(f"角色 {character_id} 不存在")

        # 验证权限
        await self.ensure_project_owner(character.project_id, user_id)
        return character

    async def update_character(
        self,
        character_id: int,
        user_id: int,
        **update_data
    ) -> BlueprintCharacter:
        """更新角色信息"""
        from ..models import BlueprintCharacter

        character = await self.get_character(character_id, user_id)

        # 更新字段
        for key, value in update_data.items():
            if hasattr(character, key):
                setattr(character, key, value)

        await self.session.commit()
        await self.session.refresh(character)
        return character

    async def upload_character_image(
        self,
        character_id: int,
        user_id: int,
        file_content: bytes,
        filename: str,
        content_type: str
    ) -> str:
        """上传角色图片,返回存储路径"""
        import os
        from pathlib import Path

        character = await self.get_character(character_id, user_id)

        # 验证文件类型
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/jpg'}
        if content_type not in allowed_types:
            raise ValueError(f"不支持的图片格式: {content_type}")

        # 验证文件大小 (2MB)
        max_size = 2 * 1024 * 1024
        if len(file_content) > max_size:
            raise ValueError(f"图片大小超过限制 (最大2MB)")

        # 生成文件路径
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        if ext not in {'jpg', 'jpeg', 'png', 'webp'}:
            ext = 'jpg'

        file_name = f"{character.project_id}_{character_id}.{ext}"

        # 创建目录
        upload_dir = Path("uploads/characters")
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path = upload_dir / file_name

        # 删除旧图片
        if character.image_path:
            old_path = Path(character.image_path)
            if old_path.exists():
                old_path.unlink()

        # 保存新图片
        with open(file_path, 'wb') as f:
            f.write(file_content)

        # 更新数据库
        relative_path = f"/uploads/characters/{file_name}"
        character.image_path = relative_path
        await self.session.commit()

        return relative_path

    async def delete_character_image(
        self,
        character_id: int,
        user_id: int
    ) -> None:
        """删除角色图片"""
        from pathlib import Path

        character = await self.get_character(character_id, user_id)

        if character.image_path:
            file_path = Path(character.image_path.lstrip('/'))
            if file_path.exists():
                file_path.unlink()

            character.image_path = None
            await self.session.commit()

    async def get_character_groups(
        self,
        project_id: str,
        user_id: int
    ) -> List[str]:
        """获取项目中所有使用的分组类型"""
        from ..models import BlueprintCharacter

        await self.ensure_project_owner(project_id, user_id)

        stmt = (
            select(BlueprintCharacter.group_type)
            .where(
                BlueprintCharacter.project_id == project_id,
                BlueprintCharacter.group_type.isnot(None),
                BlueprintCharacter.group_type != ""
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        groups = [row[0] for row in result.all()]
        return sorted(groups)

    async def batch_update_character_group(
        self,
        project_id: str,
        user_id: int,
        old_group: str,
        new_group: str
    ) -> int:
        """批量更新角色分组(用于重命名分组)"""
        from sqlalchemy import update
        from ..models import BlueprintCharacter

        await self.ensure_project_owner(project_id, user_id)

        stmt = (
            update(BlueprintCharacter)
            .where(
                BlueprintCharacter.project_id == project_id,
                BlueprintCharacter.group_type == old_group
            )
            .values(group_type=new_group)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        return result.rowcount

