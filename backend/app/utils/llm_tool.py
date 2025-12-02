# -*- coding: utf-8 -*-
"""OpenAI 兼容型 LLM 工具封装，保持与旧项目一致的接口体验。"""

import os
from dataclasses import asdict, dataclass
from typing import AsyncGenerator, Dict, List, Optional

import httpx
from openai import AsyncOpenAI


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class LLMClient:
    """异步流式调用封装，兼容 OpenAI SDK。"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("缺少 OPENAI_API_KEY 配置，请在数据库或环境变量中补全。")

        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url or os.environ.get("OPENAI_API_BASE"),
        )

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        response_format: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 300,
        **kwargs,
    ) -> AsyncGenerator[Dict[str, str], None]:
        payload = {
            "model": model or os.environ.get("MODEL", "gpt-3.5-turbo"),
            "messages": [msg.to_dict() for msg in messages],
            "stream": True,
            **kwargs,
        }
        if response_format:
            payload["response_format"] = {"type": response_format}
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # 使用 httpx.Timeout 配置超时：连接超时 60 秒，读取超时使用传入参数
        request_timeout = httpx.Timeout(timeout, connect=60.0)
        stream = await self._client.chat.completions.create(timeout=request_timeout, **payload)
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            yield {
                "content": choice.delta.content,
                "finish_reason": choice.finish_reason,
            }
