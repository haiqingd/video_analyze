"""GLM（智谱 OpenAI 兼容接口）调用：分段笔记 + 最终攻略生成。"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from .config import Settings

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

STYLE_BRIEF = "brief"
STYLE_STANDARD = "standard"
STYLE_DETAILED = "detailed"

STYLE_HINTS = {
    STYLE_BRIEF: "极简风格：只保留「一句话总评 + 核心要点 + 攻略步骤（带时间戳）」，总量 600 字以内。",
    STYLE_STANDARD: "标准风格：完整保留输出结构，总量控制在 1800 字以内。重点突出，但关键操作与数值要写全。",
    STYLE_DETAILED: "详细风格：完整保留输出结构，总量控制在 3500 字以内；步骤覆盖到每个游戏日，机制速查尽量全。",
}


class LLMError(Exception):
    pass


class GLMClient:
    def __init__(self, api_key: str, model: str, base_url: str):
        if not api_key:
            raise LLMError("未配置 GLM API Key，请在设置或 .env 中填写")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def chat(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 8192) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 总结任务不需要深度思考；开着会耗尽输出 token 导致空内容
            "thinking": {"type": "disabled"},
        }
        last_err: Exception | None = None
        backoffs = (0, 5, 15, 30)
        content_filter_temp = [None, 0.3, 0.7, 1.0]  # 内容风控是随机拦截，逐次升 temperature 制造输出变化
        note_added = False
        for attempt, backoff in enumerate(backoffs, 1):
            if backoff:
                time.sleep(backoff)
            try:
                with _llm_mutex:
                    r = httpx.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        timeout=600,
                    )
            except httpx.HTTPError as e:
                last_err = e
                continue
            if r.status_code == 429 or r.status_code >= 500:
                # 429 限流：编码套餐并发额度低，退避要更长
                last_err = LLMError(f"GLM 接口返回 {r.status_code}（限流/服务端错误）")
                time.sleep(20 * attempt)
                continue
            if r.status_code != 200:
                try:
                    msg = r.json().get("error", {}).get("message") or r.text[:300]
                except Exception:
                    msg = r.text[:300]
                # 内容风控误伤（游戏术语如"稳赢/赌/齐币"易触发，且为随机拦截）：
                # 附加游戏语境说明 + 逐步升温重试
                if r.status_code == 400 and "敏感" in msg and attempt < len(backoffs):
                    if not note_added:
                        note_added = True
                        payload["messages"] = [
                            payload["messages"][0],
                            {"role": "user", "content": "（说明：以下全部是游戏《星露谷物语》攻略视频的字幕与笔记，"
                             "涉及「赌、赢、币」等词均为游戏机制描述，无现实敏感内容。）\n\n" + user},
                        ]
                    t = content_filter_temp[attempt] or temperature
                    payload["temperature"] = t
                    last_err = LLMError(f"GLM 内容风控：{msg[:60]}")
                    continue
                raise LLMError(f"GLM 接口返回 {r.status_code}：{msg}")
            data = r.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            if content and content.strip():
                return content.strip()
            last_err = LLMError("GLM 返回了空内容")
        raise LLMError(f"GLM 调用失败（已重试 {len(backoffs)} 次）：{last_err}")


# 编码套餐的并发额度有限，全局串行化 LLM 调用
_llm_mutex = threading.Lock()


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def summarize_transcript(
    client: GLMClient,
    video_title: str,
    uploader: str,
    duration_sec: int,
    cues: list[dict],
    style: str = STYLE_STANDARD,
    log: Callable[[str], None] | None = None,
    final_client: GLMClient | None = None,
    reference: str = "",
) -> str:
    """转写稿 → 攻略 Markdown。三阶段：

    1. 关键事实抽取：直接读完整文稿（避免分段损耗），抄录全部数值/规划/机制
    2. 分段笔记：长文稿逐段提炼（补充上下文连续性）
    3. 最终合成：事实清单 + 笔记 → 攻略（用更强的模型）
    """
    from .transcript import chunk_lines, cues_to_lines, fmt_ts

    log = log or (lambda _msg: None)
    lines = cues_to_lines(cues)
    full_text = "\n".join(lines)
    meta_line = f"视频标题：{video_title}\nUP主：{uploader}\n视频时长：{fmt_ts(duration_sec)}"

    # 阶段 1：关键事实抽取（读完整文稿）
    log(f"关键事实抽取（完整文稿 {len(lines)} 行）…")
    facts = client.chat(_load_prompt("facts.md"), f"{meta_line}\n\n===== 完整字幕文稿 =====\n{full_text}")

    # 阶段 2：分段笔记（仅长文稿，补充时间顺序上下文）
    notes: list[str] = []
    chunks = chunk_lines(lines)
    if len(chunks) > 1:
        chunk_system = _load_prompt("chunk.md")
        for i, chunk in enumerate(chunks, 1):
            span = f"{chunk[0].split(']')[0][1:]} ~ {chunk[-1].split(']')[0][1:]}"
            log(f"分段总结 {i}/{len(chunks)}（{span}，{len(chunk)} 行）")
            user = f"{meta_line}\n\n===== 字幕文稿 第{i}段/共{len(chunks)}段（{span}） =====\n" + "\n".join(chunk)
            notes.append(f"### 第 {i} 段（{span}）\n" + client.chat(chunk_system, user))

    # 阶段 3：最终合成（强模型；内容风控被拦时换回基础模型兜底）
    synth = final_client or client
    log(f"合成最终攻略（{synth.model}）…")
    system = _load_prompt("final.md")
    user = (
        f"{meta_line}\n\n风格要求：{STYLE_HINTS.get(style, STYLE_HINTS[STYLE_STANDARD])}\n\n"
        f"===== 材料一：关键事实清单（写作素材底座，正文应尽量完整覆盖） =====\n\n{facts}"
    )
    if notes:
        user += f"\n\n===== 材料二：分段笔记 =====\n\n" + "\n\n".join(notes)
    # 材料三：UP主本人整理的文字版攻略（用户在页面填写链接，实时抓取）
    if reference and reference.strip():
        user += (
            "\n\n===== 材料三：UP主本人整理的文字版攻略"
            "（术语与数值以此为准，叙事与结构以视频文稿为准） =====\n\n" + reference.strip()[:9000]
        )
    try:
        return synth.chat(system, user)
    except LLMError as e:
        if "内容风控" in str(e) and synth is not client:
            log(f"⚠ {synth.model} 被内容风控拦截，回退 {client.model} 重试")
            return client.chat(system, user)
        raise


_TS_RE = re.compile(r"\b([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?\b")


def ts_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0] * 60 + parts[1]


def seconds_to_ts(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _caption_from_line(line: str) -> str:
    """从带时间戳的行提取简洁标题：优先 **加粗** 标题，否则去符号截断。"""
    m = _BOLD_RE.search(line)
    if m:
        cap = m.group(1).strip()
        if cap:
            return cap[:30]
    text = _TS_RE.sub("", line)
    text = text.lstrip("#*-0123456789. ").replace("**", "").replace("`", "")
    text = text.strip(" ·-—|:：，,、")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:40] or "关键画面"


def extract_key_moments(markdown: str, duration_sec: int, limit: int = 6, min_gap: int = 15) -> list[dict]:
    """从攻略 Markdown 中提取截图时间点。

    多天内容的视频（如春5+春6）关键步骤集中在每天开头，顺序扫描会挤在前段；
    改为把视频时长均分为 limit 段、每段取段内首个时间戳，保证截图覆盖全程，
    不足再从剩余时刻补齐。
    """
    # 顺序收集全部带时间戳的行
    candidates: list[tuple[int, str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((">", "!")):
            continue
        m = _TS_RE.search(stripped)
        if not m:
            continue
        try:
            sec = ts_to_seconds(m.group(0))
        except ValueError:
            continue
        if sec >= max(duration_sec - 2, 1):
            continue
        candidates.append((sec, stripped))

    picked: list[tuple[int, str]] = []

    def far_enough(sec: int) -> bool:
        return all(abs(sec - p[0]) >= min_gap for p in picked)

    # 均匀分段采样
    seg = max(duration_sec, 1) / max(limit, 1)
    for i in range(limit):
        lo, hi = i * seg, (i + 1) * seg
        for sec, line in candidates:
            if lo <= sec < hi and sec not in [p[0] for p in picked] and far_enough(sec):
                picked.append((sec, line))
                break
    # 不足补齐
    for sec, line in candidates:
        if len(picked) >= limit:
            break
        if sec not in [p[0] for p in picked] and far_enough(sec):
            picked.append((sec, line))
    picked.sort(key=lambda p: p[0])
    return [
        {"t": sec, "ts": seconds_to_ts(sec), "caption": _caption_from_line(line)}
        for sec, line in picked
    ]
