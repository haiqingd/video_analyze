"""字幕 cue 列表 → LLM 友好的分块文稿。"""
from __future__ import annotations

from typing import Any


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def cues_to_lines(cues: list[dict[str, Any]]) -> list[str]:
    """每条 cue 一行：`[mm:ss] 文本`。"""
    return [f"[{fmt_ts(c['start'])}] {c['text']}" for c in cues]


def chunk_lines(lines: list[str], max_chars: int = 9000) -> list[list[str]]:
    """按字符量分块，尽量不打断相邻行。"""
    chunks: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > max_chars and cur:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append(cur)
    return chunks
