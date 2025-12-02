import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from fastapi import HTTPException, status
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError

from ..core.config import settings
from ..repositories.llm_config_repository import LLMConfigRepository
from ..repositories.system_config_repository import SystemConfigRepository
from ..repositories.user_repository import UserRepository
from ..services.admin_setting_service import AdminSettingService
from ..services.prompt_service import PromptService
from ..services.usage_service import UsageService
from ..utils.json_utils import remove_think_tags, safe_parse_json, unwrap_markdown_json
from ..utils.llm_tool import ChatMessage, LLMClient

logger = logging.getLogger(__name__)


@dataclass
class SegmentParseError:
    """分段解析失败时的错误信息。"""
    segment_name: str
    segment_index: int
    raw_response: str
    error_message: str
    error_position: Optional[int] = None


@dataclass
class BlueprintGenerationResult:
    """蓝图生成结果，支持成功和需要修复两种状态。"""
    success: bool
    blueprint: Optional[Dict[str, Any]] = None
    error: Optional[SegmentParseError] = None
    partial_blueprint: Optional[Dict[str, Any]] = None
    generation_context: Optional[Dict[str, Any]] = None


# 蓝图分段生成的指令模板
BLUEPRINT_SEGMENT_INSTRUCTIONS = {
    "basic": """现在请只生成蓝图的基础信息部分。

基于对话中讨论的创意，输出一个 JSON 对象，包含以下字段：
- title: 小说标题（引人入胜，体现故事核心）
- target_audience: 目标读者群体
- genre: 类型（如玄幻、都市、言情等）
- style: 写作风格（如轻松幽默、严肃深沉、热血激昂等）
- tone: 整体基调
- one_sentence_summary: 一句话概括故事核心冲突和吸引点
- full_synopsis: 完整故事梗概（300-500字，包含起承转合）

要求：内容要充满人性温度和创作灵感，不能有程式化的 AI 痕迹。
只输出 JSON，不要添加任何解释。""",

    "world_setting": """现在请只生成蓝图的世界观设定部分。

基于已生成的基础信息，构建一个沉浸式的故事世界，输出 JSON：
{
  "world_setting": {
    "core_rules": "世界运行的核心规则/设定（如修炼体系、社会制度、魔法规则等）",
    "key_locations": [
      {"name": "地点名称", "description": "详细描述，包含氛围、特色、在故事中的作用"}
    ],
    "factions": [
      {"name": "势力/组织名称", "description": "势力特点、立场、与主角的关系"}
    ]
  }
}

要求：
- 世界设定要有内在逻辑，自洽且有深度
- 地点和势力要与故事发展紧密关联
- 营造让读者仿佛置身其中的氛围
只输出 JSON，不要添加任何解释。""",

    "characters": """现在请只生成蓝图的角色部分。

基于故事梗概和世界观，创造有血有肉的角色群像，输出 JSON：
{
  "characters": [
    {
      "name": "角色姓名",
      "identity": "身份/职业/地位",
      "personality": "性格特点（包含优点、缺陷、独特之处）",
      "goals": "核心目标和动机（要有层次，表面目标和深层渴望）",
      "abilities": "能力/技能/特长",
      "relationship_to_protagonist": "与主角的关系和互动方式"
    }
  ]
}

角色塑造要求：
- 每个角色都要有独特的声音、行为模式和动机
- 赋予角色真实的背景故事和情感创伤
- 角色要有缺陷、有欲望、有秘密、有成长弧线
- 配角也要有自己的完整弧线，不只是功能性存在
- 设计角色间的化学反应和潜在冲突点

只输出 JSON，不要添加任何解释。""",

    "relationships": """现在请只生成蓝图的角色关系部分。

基于已生成的角色列表，构建真实可信的人际关系网络，输出 JSON：
{
  "relationships": [
    {
      "character_from": "角色A姓名",
      "character_to": "角色B姓名",
      "description": "关系描述（包含关系性质、情感张力、潜在冲突或羁绊）"
    }
  ]
}

关系设计要求：
- 关系网络要充满张力和复杂性
- 包含多种关系类型：亲情、友情、爱情、对立、暧昧、利用等
- 每段关系都要有发展空间和戏剧潜力
- 注意关系的对称性（A对B和B对A可能不同）

只输出 JSON，不要添加任何解释。""",

    "chapter_outline": """现在请生成章节大纲部分。

基于故事梗概、角色设定和世界观，输出从第 {start} 章到第 {end} 章的大纲 JSON：
{{
  "chapters": [
    {{
      "chapter_number": 1,
      "title": "章节标题（要有吸引力，暗示本章看点）",
      "summary": "章节摘要（50-100字，包含本章核心事件、情感转折、悬念钩子）"
    }}
  ]
}}

情节构建要求：
- 基于角色驱动的故事发展，而非单纯的事件堆砌
- 设置情感高潮和转折点
- 每章都要推进角色成长或揭示新的秘密
- 创造让读者欲罢不能的悬念和情感钩子
- 注意与前后章节的连贯性

只输出 JSON，不要添加任何解释。"""
}

try:  # pragma: no cover - 运行环境未安装时兼容
    from ollama import AsyncClient as OllamaAsyncClient
except ImportError:  # pragma: no cover - Ollama 为可选依赖
    OllamaAsyncClient = None


class LLMService:
    """封装与大模型交互的所有逻辑，包括配额控制与配置选择。"""

    def __init__(self, session):
        self.session = session
        self.llm_repo = LLMConfigRepository(session)
        self.system_config_repo = SystemConfigRepository(session)
        self.user_repo = UserRepository(session)
        self.admin_setting_service = AdminSettingService(session)
        self.usage_service = UsageService(session)
        self._embedding_dimensions: Dict[str, int] = {}

    async def get_llm_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        user_id: Optional[int] = None,
        timeout: float = 300.0,
        response_format: Optional[str] = "json_object",
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}, *conversation_history]
        return await self._stream_and_collect(
            messages,
            temperature=temperature,
            user_id=user_id,
            timeout=timeout,
            response_format=response_format,
        )

    async def get_summary(
        self,
        chapter_content: str,
        *,
        temperature: float = 0.2,
        user_id: Optional[int] = None,
        timeout: float = 180.0,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not system_prompt:
            prompt_service = PromptService(self.session)
            system_prompt = await prompt_service.get_prompt("extraction")
        if not system_prompt:
            logger.error("未配置名为 'extraction' 的摘要提示词，无法生成章节摘要")
            raise HTTPException(status_code=500, detail="未配置摘要提示词，请联系管理员配置 'extraction' 提示词")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chapter_content},
        ]
        return await self._stream_and_collect(messages, temperature=temperature, user_id=user_id, timeout=timeout)

    async def _stream_and_collect(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float,
        user_id: Optional[int],
        timeout: float,
        response_format: Optional[str] = None,
        auto_continue: bool = True,
        max_continuations: int = 5,
    ) -> str:
        """流式收集 LLM 响应，支持自动续写。

        Args:
            messages: 对话消息列表
            temperature: 生成温度
            user_id: 用户 ID
            timeout: 超时时间（秒）
            response_format: 响应格式（如 json_object）
            auto_continue: 是否启用自动续写（当响应被截断时自动继续）
            max_continuations: 最大续写次数，防止无限循环
        """
        config = await self._resolve_llm_config(user_id)
        client = LLMClient(api_key=config["api_key"], base_url=config.get("base_url"))

        full_response = ""
        continuation_count = 0
        current_messages = list(messages)  # 复制消息列表

        while True:
            chat_messages = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in current_messages]
            segment_response = ""
            finish_reason = None

            logger.info(
                "Streaming LLM response: model=%s user_id=%s messages=%d continuation=%d",
                config.get("model"),
                user_id,
                len(current_messages),
                continuation_count,
            )

            try:
                async for part in client.stream_chat(
                    messages=chat_messages,
                    model=config.get("model"),
                    temperature=temperature,
                    timeout=int(timeout),
                    response_format=response_format,
                ):
                    if part.get("content"):
                        segment_response += part["content"]
                    if part.get("finish_reason"):
                        finish_reason = part["finish_reason"]
            except InternalServerError as exc:
                detail = "AI 服务内部错误，请稍后重试"
                response = getattr(exc, "response", None)
                if response is not None:
                    try:
                        payload = response.json()
                        error_data = payload.get("error", {}) if isinstance(payload, dict) else {}
                        detail = error_data.get("message_zh") or error_data.get("message") or detail
                    except Exception:
                        detail = str(exc) or detail
                else:
                    detail = str(exc) or detail
                logger.error(
                    "LLM stream internal error: model=%s user_id=%s detail=%s",
                    config.get("model"),
                    user_id,
                    detail,
                    exc_info=exc,
                )
                raise HTTPException(status_code=503, detail=detail)
            except (httpx.RemoteProtocolError, httpx.ReadTimeout, APIConnectionError, APITimeoutError) as exc:
                if isinstance(exc, httpx.RemoteProtocolError):
                    detail = "AI 服务连接被意外中断，请稍后重试"
                elif isinstance(exc, (httpx.ReadTimeout, APITimeoutError)):
                    detail = "AI 服务响应超时，请稍后重试"
                else:
                    detail = "无法连接到 AI 服务，请稍后重试"
                logger.error(
                    "LLM stream failed: model=%s user_id=%s detail=%s",
                    config.get("model"),
                    user_id,
                    detail,
                    exc_info=exc,
                )
                raise HTTPException(status_code=503, detail=detail) from exc

            full_response += segment_response

            logger.debug(
                "LLM response segment: model=%s user_id=%s finish_reason=%s segment_len=%d total_len=%d",
                config.get("model"),
                user_id,
                finish_reason,
                len(segment_response),
                len(full_response),
            )

            # 检查是否需要续写
            if finish_reason == "length" and auto_continue and continuation_count < max_continuations:
                continuation_count += 1
                logger.info(
                    "LLM response truncated, auto-continuing: model=%s user_id=%s continuation=%d/%d current_len=%d",
                    config.get("model"),
                    user_id,
                    continuation_count,
                    max_continuations,
                    len(full_response),
                )
                # 添加已生成的内容作为助手消息，并请求继续
                current_messages = list(messages)  # 重置为原始消息
                current_messages.append({"role": "assistant", "content": segment_response})
                # 针对 JSON 格式响应使用更明确的续写指令
                if response_format == "json_object":
                    current_messages.append({
                        "role": "user",
                        "content": "请从你上次输出中断的地方继续，直接输出剩余的 JSON 内容，不要重复已输出的部分，不要添加任何解释。"
                    })
                else:
                    current_messages.append({"role": "user", "content": "请继续"})
                continue
            elif finish_reason == "length":
                # 已达到最大续写次数，记录警告但返回已收集的内容
                logger.warning(
                    "LLM response still truncated after max continuations: model=%s user_id=%s continuations=%d total_len=%d",
                    config.get("model"),
                    user_id,
                    continuation_count,
                    len(full_response),
                )
                break
            else:
                # 正常结束
                break

        if not full_response:
            logger.error(
                "LLM returned empty response: model=%s user_id=%s finish_reason=%s",
                config.get("model"),
                user_id,
                finish_reason,
            )
            raise HTTPException(
                status_code=500,
                detail=f"AI 未返回有效内容（结束原因: {finish_reason or '未知'}），请稍后重试或联系管理员"
            )

        await self.usage_service.increment("api_request_count")
        if continuation_count > 0:
            # 续写时多次请求，按实际请求次数计费
            for _ in range(continuation_count):
                await self.usage_service.increment("api_request_count")

        logger.info(
            "LLM response success: model=%s user_id=%s chars=%d continuations=%d",
            config.get("model"),
            user_id,
            len(full_response),
            continuation_count,
        )
        return full_response

    async def _resolve_llm_config(self, user_id: Optional[int]) -> Dict[str, Optional[str]]:
        if user_id:
            config = await self.llm_repo.get_by_user(user_id)
            if config and config.llm_provider_api_key:
                return {
                    "api_key": config.llm_provider_api_key,
                    "base_url": config.llm_provider_url,
                    "model": config.llm_provider_model,
                }

        # 检查每日使用次数限制
        if user_id:
            await self._enforce_daily_limit(user_id)

        api_key = await self._get_config_value("llm.api_key")
        base_url = await self._get_config_value("llm.base_url")
        model = await self._get_config_value("llm.model")

        if not api_key:
            logger.error("未配置默认 LLM API Key，且用户 %s 未设置自定义 API Key", user_id)
            raise HTTPException(
                status_code=500,
                detail="未配置默认 LLM API Key，请联系管理员配置系统默认 API Key 或在个人设置中配置自定义 API Key"
            )

        return {"api_key": api_key, "base_url": base_url, "model": model}

    async def get_embedding(
        self,
        text: str,
        *,
        user_id: Optional[int] = None,
        model: Optional[str] = None,
    ) -> List[float]:
        """生成文本向量，用于章节 RAG 检索，支持 openai 与 ollama 双提供方。"""
        provider = await self._get_config_value("embedding.provider") or "openai"
        default_model = (
            await self._get_config_value("ollama.embedding_model") or "nomic-embed-text:latest"
            if provider == "ollama"
            else await self._get_config_value("embedding.model") or "text-embedding-3-large"
        )
        target_model = model or default_model

        if provider == "ollama":
            if OllamaAsyncClient is None:
                logger.error("未安装 ollama 依赖，无法调用本地嵌入模型。")
                raise HTTPException(status_code=500, detail="缺少 Ollama 依赖，请先安装 ollama 包。")

            base_url = (
                await self._get_config_value("ollama.embedding_base_url")
                or await self._get_config_value("embedding.base_url")
            )
            client = OllamaAsyncClient(host=base_url)
            try:
                response = await client.embeddings(model=target_model, prompt=text)
            except Exception as exc:  # pragma: no cover - 本地服务调用失败
                logger.error(
                    "Ollama 嵌入请求失败: model=%s base_url=%s error=%s",
                    target_model,
                    base_url,
                    exc,
                    exc_info=True,
                )
                return []
            embedding: Optional[List[float]]
            if isinstance(response, dict):
                embedding = response.get("embedding")
            else:
                embedding = getattr(response, "embedding", None)
            if not embedding:
                logger.warning("Ollama 返回空向量: model=%s", target_model)
                return []
            if not isinstance(embedding, list):
                embedding = list(embedding)
        else:
            config = await self._resolve_llm_config(user_id)
            api_key = await self._get_config_value("embedding.api_key") or config["api_key"]
            base_url = await self._get_config_value("embedding.base_url") or config.get("base_url")
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            try:
                response = await client.embeddings.create(
                    input=text,
                    model=target_model,
                )
            except Exception as exc:  # pragma: no cover - 网络或鉴权失败
                logger.error(
                    "OpenAI 嵌入请求失败: model=%s base_url=%s user_id=%s error=%s",
                    target_model,
                    base_url,
                    user_id,
                    exc,
                    exc_info=True,
                )
                return []
            if not response.data:
                logger.warning("OpenAI 嵌入请求返回空数据: model=%s user_id=%s", target_model, user_id)
                return []
            embedding = response.data[0].embedding

        if not isinstance(embedding, list):
            embedding = list(embedding)

        dimension = len(embedding)
        if not dimension:
            vector_size_str = await self._get_config_value("embedding.model_vector_size")
            if vector_size_str:
                dimension = int(vector_size_str)
        if dimension:
            self._embedding_dimensions[target_model] = dimension
        return embedding

    async def get_embedding_dimension(self, model: Optional[str] = None) -> Optional[int]:
        """获取嵌入向量维度，优先返回缓存结果，其次读取配置。"""
        provider = await self._get_config_value("embedding.provider") or "openai"
        default_model = (
            await self._get_config_value("ollama.embedding_model") or "nomic-embed-text:latest"
            if provider == "ollama"
            else await self._get_config_value("embedding.model") or "text-embedding-3-large"
        )
        target_model = model or default_model
        if target_model in self._embedding_dimensions:
            return self._embedding_dimensions[target_model]
        vector_size_str = await self._get_config_value("embedding.model_vector_size")
        return int(vector_size_str) if vector_size_str else None

    async def _enforce_daily_limit(self, user_id: int) -> None:
        limit_str = await self.admin_setting_service.get("daily_request_limit", "100")
        limit = int(limit_str or 10)
        used = await self.user_repo.get_daily_request(user_id)
        if used >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="今日请求次数已达上限，请明日再试或设置自定义 API Key。",
            )
        await self.user_repo.increment_daily_request(user_id)
        await self.session.commit()

    async def _get_config_value(self, key: str) -> Optional[str]:
        record = await self.system_config_repo.get_by_key(key)
        if record:
            return record.value
        # 兼容环境变量，首次迁移时无需立即写入数据库
        env_key = key.upper().replace(".", "_")
        return os.getenv(env_key)

    async def _generate_segment_with_retry(
        self,
        segment_name: str,
        segment_index: int,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_id: Optional[int],
        temperature: float = 0.3,
        timeout: float = 180.0,
        max_retries: int = 1,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[SegmentParseError]]:
        """生成单个分段并解析，支持失败重试。

        Args:
            segment_name: 段名称（用于日志和错误提示）
            segment_index: 段索引（1-5）
            system_prompt: 系统提示词
            conversation_history: 对话历史
            user_id: 用户 ID
            temperature: 生成温度
            timeout: 超时时间
            max_retries: 最大重试次数（默认1次，即最多尝试2次）

        Returns:
            (解析后的数据, None) 成功时
            (None, SegmentParseError) 失败时
        """
        last_error_msg = ""
        last_error_pos = None
        last_response = ""

        for attempt in range(max_retries + 1):
            try:
                # 如果是重试，添加修复提示
                if attempt > 0:
                    logger.info(
                        "分段 %s 第 %d 次重试 user_id=%s",
                        segment_name,
                        attempt,
                        user_id,
                    )
                    # 添加修复提示到对话历史
                    retry_history = conversation_history + [
                        {
                            "role": "user",
                            "content": (
                                f"你上次的输出有 JSON 格式错误：{last_error_msg}\n"
                                "请重新输出，注意：\n"
                                "1. 确保所有字符串中的引号、换行符都正确转义\n"
                                "2. 不要在 JSON 中使用未转义的特殊字符\n"
                                "3. 只输出纯 JSON，不要有任何额外文字"
                            ),
                        }
                    ]
                else:
                    retry_history = conversation_history

                response = await self.get_llm_response(
                    system_prompt=system_prompt,
                    conversation_history=retry_history,
                    temperature=temperature,
                    user_id=user_id,
                    timeout=timeout,
                )
                last_response = response

                # 尝试解析
                result, error_msg, error_pos = self._parse_segment_response_with_error(response, segment_name)
                if result:
                    return result, None

                # 解析失败，记录错误
                last_error_msg = error_msg or "解析结果为空"
                last_error_pos = error_pos

            except HTTPException:
                raise
            except Exception as exc:
                last_error_msg = str(exc)
                logger.warning(
                    "分段 %s 生成异常 (attempt %d/%d): %s",
                    segment_name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

        # 重试耗尽，返回错误信息（让用户手动修复）
        logger.warning(
            "分段 %s 自动重试耗尽，返回给用户手动修复\n错误: %s\n响应长度: %d",
            segment_name,
            last_error_msg,
            len(last_response),
        )
        return None, SegmentParseError(
            segment_name=segment_name,
            segment_index=segment_index,
            raw_response=last_response,
            error_message=last_error_msg,
            error_position=last_error_pos,
        )

    def _parse_segment_response_with_error(
        self, response: str, segment_name: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
        """解析分段响应，返回结果和错误信息。

        Returns:
            (解析结果, 错误信息, 错误位置)
            成功时: (dict, None, None)
            失败时: (None, error_msg, error_pos)
        """
        cleaned = remove_think_tags(response)
        normalized = unwrap_markdown_json(cleaned)

        # 第一次尝试：直接解析
        try:
            data = json.loads(normalized)
            return self._normalize_segment_data(data, segment_name), None, None
        except json.JSONDecodeError as exc:
            first_error_msg = f"{exc.msg}"
            first_error_pos = exc.pos
            logger.warning(
                "分段 %s 首次解析失败: %s (位置: %d)\n内容预览: %s",
                segment_name,
                exc.msg,
                exc.pos,
                normalized[max(0, exc.pos - 50) : exc.pos + 50] if exc.pos else normalized[:100],
            )

        # 第二次尝试：使用 safe_parse_json（包含清洗逻辑）
        result = safe_parse_json(response)
        if result:
            logger.info("分段 %s 使用 safe_parse_json 解析成功", segment_name)
            return self._normalize_segment_data(result, segment_name), None, None

        # 第三次尝试：手动修复常见问题
        try:
            fixed = self._try_fix_json(normalized)
            data = json.loads(fixed)
            logger.info("分段 %s 使用修复逻辑解析成功", segment_name)
            return self._normalize_segment_data(data, segment_name), None, None
        except json.JSONDecodeError:
            pass

        # 所有尝试都失败
        logger.error(
            "分段 %s 所有解析尝试都失败\n原始响应长度: %d",
            segment_name,
            len(response),
        )
        return None, first_error_msg, first_error_pos

    def _normalize_segment_data(self, data: Any, segment_name: str) -> Dict[str, Any]:
        """标准化分段数据为字典格式。"""
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            field_map = {
                "characters": "characters",
                "relationships": "relationships",
                "chapter_outline": "chapters",
            }
            field_name = field_map.get(segment_name, segment_name)
            logger.info("分段 %s 返回数组，包装为 {%s: [...]}", segment_name, field_name)
            return {field_name: data}
        logger.warning("分段 %s 返回非字典/数组类型: %s", segment_name, type(data))
        return {}

    def _try_fix_json(self, text: str) -> str:
        """尝试修复常见的 JSON 格式问题。"""
        import re

        fixed = text

        # 修复未转义的换行符（在字符串内部）
        # 这是一个简化的修复，可能不完美
        def fix_newlines_in_strings(match):
            content = match.group(1)
            # 替换未转义的换行
            content = content.replace('\n', '\\n')
            content = content.replace('\r', '\\r')
            content = content.replace('\t', '\\t')
            return f'"{content}"'

        # 匹配 JSON 字符串（简化版，可能有边界情况）
        # 这个正则尝试匹配 "..." 中的内容，但不包括已转义的引号
        try:
            # 更安全的方式：逐字符处理
            fixed = self._fix_json_strings(text)
        except Exception:
            pass

        return fixed

    def _fix_json_strings(self, text: str) -> str:
        """逐字符修复 JSON 字符串中的问题。"""
        result = []
        i = 0
        in_string = False
        escape_next = False

        while i < len(text):
            char = text[i]

            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue

            if char == '\\':
                result.append(char)
                escape_next = True
                i += 1
                continue

            if char == '"':
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if in_string:
                # 在字符串内，转义特殊字符
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
                else:
                    result.append(char)
            else:
                result.append(char)

            i += 1

        return ''.join(result)

    async def generate_blueprint_in_segments(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        total_chapters: int = 20,
        *,
        user_id: Optional[int] = None,
        chapters_per_batch: int = 50,
        start_from_segment: int = 1,
        partial_blueprint: Optional[Dict[str, Any]] = None,
    ) -> BlueprintGenerationResult:
        """分段生成小说蓝图，避免单次请求过长导致截断。

        将蓝图拆分为多个部分分别生成：
        1. 基础信息（title, genre, style 等）
        2. 世界观设定（world_setting）
        3. 角色（characters）
        4. 角色关系（relationships）
        5. 章节大纲（chapter_outline）- 按批次生成

        Args:
            system_prompt: 原始的蓝图生成系统提示词
            conversation_history: 对话历史
            total_chapters: 总章节数
            user_id: 用户 ID
            chapters_per_batch: 每批生成的章节数，默认 50
            start_from_segment: 从第几段开始（用于恢复生成）
            partial_blueprint: 已有的部分蓝图（用于恢复生成）

        Returns:
            BlueprintGenerationResult，包含成功的蓝图或需要修复的错误信息
        """
        blueprint: Dict[str, Any] = partial_blueprint.copy() if partial_blueprint else {}
        char_names: List[str] = []

        # 定义段信息
        segment_names = ["basic", "world_setting", "characters", "relationships", "chapter_outline"]

        # 段1: 生成基础信息
        if start_from_segment <= 1:
            logger.info("分段生成蓝图 [1/5]: 基础信息 user_id=%s", user_id)
            basic_prompt = f"{system_prompt}\n\n{BLUEPRINT_SEGMENT_INSTRUCTIONS['basic']}"
            basic_data, error = await self._generate_segment_with_retry(
                segment_name="basic",
                segment_index=1,
                system_prompt=basic_prompt,
                conversation_history=conversation_history,
                user_id=user_id,
                temperature=0.3,
                timeout=180.0,
            )
            if error:
                return BlueprintGenerationResult(
                    success=False,
                    error=error,
                    partial_blueprint=blueprint,
                    generation_context={
                        "system_prompt": system_prompt,
                        "total_chapters": total_chapters,
                        "chapters_per_batch": chapters_per_batch,
                    },
                )
            blueprint.update(basic_data)
            logger.info("分段生成蓝图 [1/5]: 基础信息完成，标题=%s", blueprint.get("title"))

        # 构建上下文消息
        basic_data = {k: blueprint.get(k) for k in ["title", "target_audience", "genre", "style", "tone", "one_sentence_summary", "full_synopsis"] if k in blueprint}
        context_msg = f"已生成的基础信息：\n{json.dumps(basic_data, ensure_ascii=False, indent=2)}"

        # 段2: 生成世界观设定
        if start_from_segment <= 2:
            logger.info("分段生成蓝图 [2/5]: 世界观设定 user_id=%s", user_id)
            world_prompt = f"{system_prompt}\n\n{BLUEPRINT_SEGMENT_INSTRUCTIONS['world_setting']}"
            world_history = conversation_history + [{"role": "assistant", "content": context_msg}]
            world_data, error = await self._generate_segment_with_retry(
                segment_name="world_setting",
                segment_index=2,
                system_prompt=world_prompt,
                conversation_history=world_history,
                user_id=user_id,
                temperature=0.3,
                timeout=180.0,
            )
            if error:
                return BlueprintGenerationResult(
                    success=False,
                    error=error,
                    partial_blueprint=blueprint,
                    generation_context={
                        "system_prompt": system_prompt,
                        "total_chapters": total_chapters,
                        "chapters_per_batch": chapters_per_batch,
                    },
                )
            blueprint.update(world_data)
            logger.info("分段生成蓝图 [2/5]: 世界观设定完成")

        # 更新上下文
        world_data = blueprint.get("world_setting", {})
        context_msg = f"已生成的内容：\n{json.dumps({**basic_data, 'world_setting': world_data}, ensure_ascii=False, indent=2)}"

        # 段3: 生成角色
        if start_from_segment <= 3:
            logger.info("分段生成蓝图 [3/5]: 角色 user_id=%s", user_id)
            chars_prompt = f"{system_prompt}\n\n{BLUEPRINT_SEGMENT_INSTRUCTIONS['characters']}"
            chars_history = conversation_history + [{"role": "assistant", "content": context_msg}]
            chars_data, error = await self._generate_segment_with_retry(
                segment_name="characters",
                segment_index=3,
                system_prompt=chars_prompt,
                conversation_history=chars_history,
                user_id=user_id,
                temperature=0.4,
                timeout=240.0,
            )
            if error:
                return BlueprintGenerationResult(
                    success=False,
                    error=error,
                    partial_blueprint=blueprint,
                    generation_context={
                        "system_prompt": system_prompt,
                        "total_chapters": total_chapters,
                        "chapters_per_batch": chapters_per_batch,
                    },
                )
            blueprint.update(chars_data)
            char_count = len(blueprint.get("characters", []))
            logger.info("分段生成蓝图 [3/5]: 角色完成，共 %d 个角色", char_count)

        # 更新上下文（只保留角色名称列表，避免过长）
        char_names = [c.get("name", "") for c in blueprint.get("characters", [])]
        context_msg = (
            f"已生成的基础信息：{json.dumps(basic_data, ensure_ascii=False)}\n"
            f"角色列表：{', '.join(char_names)}"
        )

        # 段4: 生成角色关系
        if start_from_segment <= 4:
            logger.info("分段生成蓝图 [4/5]: 角色关系 user_id=%s", user_id)
            rels_prompt = f"{system_prompt}\n\n{BLUEPRINT_SEGMENT_INSTRUCTIONS['relationships']}"
            rels_history = conversation_history + [{"role": "assistant", "content": context_msg}]
            rels_data, error = await self._generate_segment_with_retry(
                segment_name="relationships",
                segment_index=4,
                system_prompt=rels_prompt,
                conversation_history=rels_history,
                user_id=user_id,
                temperature=0.3,
                timeout=180.0,
            )
            if error:
                return BlueprintGenerationResult(
                    success=False,
                    error=error,
                    partial_blueprint=blueprint,
                    generation_context={
                        "system_prompt": system_prompt,
                        "total_chapters": total_chapters,
                        "chapters_per_batch": chapters_per_batch,
                    },
                )
            blueprint.update(rels_data)
            rel_count = len(blueprint.get("relationships", []))
            logger.info("分段生成蓝图 [4/5]: 角色关系完成，共 %d 条关系", rel_count)

        # 段5: 分批生成章节大纲
        if start_from_segment <= 5:
            logger.info(
                "分段生成蓝图 [5/5]: 章节大纲 user_id=%s total_chapters=%d",
                user_id,
                total_chapters,
            )
            all_chapters: List[Dict[str, Any]] = blueprint.get("chapter_outline", [])
            batch_num = len(all_chapters) // chapters_per_batch if all_chapters else 0

            # 构建大纲生成的上下文
            outline_context = (
                f"小说标题：{blueprint.get('title', '')}\n"
                f"类型：{blueprint.get('genre', '')}\n"
                f"故事梗概：{blueprint.get('full_synopsis', '')}\n"
                f"主要角色：{', '.join(char_names)}"
            )

            start_chapter = len(all_chapters) + 1
            while start_chapter <= total_chapters:
                batch_num += 1
                end_chapter = min(start_chapter + chapters_per_batch - 1, total_chapters)

                logger.info(
                    "分段生成蓝图 [5/5]: 章节大纲批次 %d，第 %d-%d 章",
                    batch_num,
                    start_chapter,
                    end_chapter,
                )

                # 构建章节大纲的指令
                outline_instruction = BLUEPRINT_SEGMENT_INSTRUCTIONS["chapter_outline"].format(
                    start=start_chapter,
                    end=end_chapter,
                )

                # 如果已有章节，添加最后几章作为上下文
                prev_context = ""
                if all_chapters:
                    last_chapters = all_chapters[-3:]
                    prev_context = "\n\n已生成的最近章节：\n" + json.dumps(
                        last_chapters, ensure_ascii=False, indent=2
                    )

                outline_prompt = f"{system_prompt}\n\n{outline_instruction}"
                outline_history = conversation_history + [
                    {"role": "assistant", "content": outline_context + prev_context}
                ]

                outline_data, error = await self._generate_segment_with_retry(
                    segment_name=f"chapter_outline_batch_{batch_num}",
                    segment_index=5,
                    system_prompt=outline_prompt,
                    conversation_history=outline_history,
                    user_id=user_id,
                    temperature=0.5,
                    timeout=300.0,
                )

                if error:
                    blueprint["chapter_outline"] = all_chapters  # 保存已有章节
                    return BlueprintGenerationResult(
                        success=False,
                        error=error,
                        partial_blueprint=blueprint,
                        generation_context={
                            "system_prompt": system_prompt,
                            "total_chapters": total_chapters,
                            "chapters_per_batch": chapters_per_batch,
                            "current_batch": batch_num,
                        },
                    )

                # 提取章节列表
                batch_chapters = outline_data.get("chapters", outline_data.get("chapter_outline", []))
                if batch_chapters:
                    all_chapters.extend(batch_chapters)
                    logger.info(
                        "分段生成蓝图 [5/5]: 批次 %d 完成，生成 %d 章，累计 %d 章",
                        batch_num,
                        len(batch_chapters),
                        len(all_chapters),
                    )
                else:
                    logger.warning(
                        "分段生成蓝图 [5/5]: 批次 %d 返回空章节列表",
                        batch_num,
                    )

                start_chapter = end_chapter + 1

            blueprint["chapter_outline"] = all_chapters

        logger.info(
            "分段生成蓝图完成: user_id=%s title=%s chapters=%d",
            user_id,
            blueprint.get("title"),
            len(blueprint.get("chapter_outline", [])),
        )

        return BlueprintGenerationResult(success=True, blueprint=blueprint)
