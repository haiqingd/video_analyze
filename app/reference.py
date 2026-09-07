"""腾讯文档参考攻略抓取：dop-api → RTF 风格 ops → 纯文本。"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path

import httpx

from .config import OUTPUT_DIR, UA


class ReferenceError(Exception):
    pass


_CACHE = OUTPUT_DIR / "cache" / "reference.json"
_TTL = 300  # 秒：批量任务短时间内复用，超过则重新拉取最新内容


def _doc_id(url: str) -> str:
    m = re.search(r"docs\.qq\.com/(?:doc|sheet)/(?:([A-Za-z0-9]+))", url)
    if not m:
        raise ReferenceError("无法从链接中解析文档 ID（目前支持 docs.qq.com/doc 分享链接）")
    return m.group(1)


def _rtf_to_text(s: str) -> str:
    # 域代码：\u0013HYPERLINK ... \u0014显示文本\u0015 → 只留显示文本
    s = re.sub("\u0013[^\u0014\u0015]*\u0014([^\u0015]*)\u0015", r"\1", s)
    s = re.sub("\u0013[^\u0015]*\u0015", "", s)
    # %uXXXX → 中文
    s = re.sub("%u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    # 其余控制字符清理（保留 \r 换行）
    s = re.sub("[\u0000-\u000c\u000e-\u001f\u007f\ufffd]", "", s)
    s = s.replace("\r", "\n")
    # 压缩空行
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch_tencent_doc(url: str, force: bool = False) -> str:
    """抓取腾讯文档（公开只读）正文文本，带 TTL 缓存。"""
    doc_id = _doc_id(url)

    if not force and _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text(encoding="utf-8"))
            if cached.get("id") == doc_id and time.time() - cached.get("ts", 0) < _TTL:
                return cached["text"]
        except (json.JSONDecodeError, OSError):
            pass

    r = httpx.get(
        "https://docs.qq.com/dop-api/opendoc",
        params={"id": doc_id, "outformat": 1, "noEscape": 1},
        headers={"User-Agent": UA, "Referer": f"https://docs.qq.com/doc/{doc_id}"},
        timeout=30,
    )
    if r.status_code != 200 or "%7B%22commands" not in r.text:
        raise ReferenceError(f"文档接口请求失败（{r.status_code}），可能不是公开文档或链接失效")
    data, _ = json.JSONDecoder().raw_decode(urllib.parse.unquote(r.text[r.text.find("%7B%22commands") :]))
    mutations = ((data.get("commands") or [{}])[0]).get("mutations") or []
    big = [m.get("s", "") for m in mutations if isinstance(m.get("s"), str) and len(m["s"]) > 500]
    if not big:
        raise ReferenceError("未能从文档数据中提取到正文")
    text = _rtf_to_text(big[0])
    if len(text) < 100:
        raise ReferenceError("文档正文过短，解析可能失败")

    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(
        json.dumps({"id": doc_id, "ts": time.time(), "text": text}, ensure_ascii=False),
        encoding="utf-8",
    )
    return text


if __name__ == "__main__":
    t = fetch_tencent_doc("https://docs.qq.com/doc/DSVBkcWpRb2NxYWxq", force=True)
    print("chars:", len(t))
    print(t[:400])
