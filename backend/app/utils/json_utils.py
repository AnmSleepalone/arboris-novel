import json
import re
from typing import Optional


def remove_think_tags(raw_text: str) -> str:
    """移除 <think></think> 标签，避免污染结果。"""
    if not raw_text:
        return raw_text
    return re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()


def unwrap_markdown_json(raw_text: str) -> str:
    """从 Markdown 或普通文本中提取 JSON 字符串。

    支持以下格式：
    1. ```json ... ``` 代码块（大小写不敏感）
    2. 裸 JSON 对象或数组
    3. 混合文本中的 JSON 片段
    """
    if not raw_text:
        return raw_text

    trimmed = raw_text.strip()

    # 优先匹配 Markdown 代码块，使用大小写不敏感模式
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", trimmed, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if candidate:
            return candidate

    # 使用括号平衡算法精确提取 JSON
    extracted = _extract_balanced_json(trimmed)
    if extracted:
        return extracted

    return trimmed


def _extract_balanced_json(text: str) -> Optional[str]:
    """使用括号平衡算法提取完整的 JSON 对象或数组。

    比简单的 find/rfind 更可靠，能正确处理嵌套结构和字符串中的括号。
    """
    # 查找第一个 { 或 [
    start_idx = -1
    start_char = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start_idx = i
            start_char = ch
            break

    if start_idx == -1:
        return None

    end_char = "}" if start_char == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_idx, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == start_char:
            depth += 1
        elif ch == end_char:
            depth -= 1
            if depth == 0:
                candidate = text[start_idx:i + 1]
                # 验证是否为有效 JSON
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    # 继续尝试下一个匹配
                    pass

    # 如果括号平衡失败，回退到简单提取
    json_start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if json_start_candidates:
        start_idx = min(json_start_candidates)
        closing_brace = text.rfind("}")
        closing_bracket = text.rfind("]")
        end_idx = max(closing_brace, closing_bracket)
        if end_idx != -1 and end_idx > start_idx:
            return text[start_idx:end_idx + 1].strip()

    return None


def sanitize_json_like_text(raw_text: str) -> str:
    """对可能含有未转义换行/引号的 JSON 文本进行清洗。

    处理 LLM 输出中常见的问题：
    - 字符串内的未转义换行符
    - 字符串内的未转义引号
    - 字符串内的制表符
    """
    if not raw_text:
        return raw_text

    result = []
    in_string = False
    escape_next = False
    length = len(raw_text)
    i = 0
    while i < length:
        ch = raw_text[i]
        if in_string:
            if escape_next:
                result.append(ch)
                escape_next = False
            elif ch == "\\":
                result.append(ch)
                escape_next = True
            elif ch == '"':
                j = i + 1
                while j < length and raw_text[j] in " \t\r\n":
                    j += 1

                if j >= length or raw_text[j] in "}]":
                    in_string = False
                    result.append(ch)
                elif raw_text[j] in ",:":
                    in_string = False
                    result.append(ch)
                else:
                    result.extend(["\\", '"'])
            elif ch == "\n":
                result.extend(["\\", "n"])
            elif ch == "\r":
                result.extend(["\\", "r"])
            elif ch == "\t":
                result.extend(["\\", "t"])
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
            result.append(ch)
        i += 1

    return "".join(result)


def safe_parse_json(raw_text: str) -> Optional[dict]:
    """安全地解析 JSON，自动尝试清洗和修复。

    解析流程：
    1. 移除 think 标签
    2. 提取 JSON 片段
    3. 尝试直接解析
    4. 解析失败则清洗后重试
    """
    if not raw_text:
        return None

    # 预处理
    cleaned = remove_think_tags(raw_text)
    extracted = unwrap_markdown_json(cleaned)

    # 第一次尝试直接解析
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass

    # 清洗后重试
    sanitized = sanitize_json_like_text(extracted)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        return None
