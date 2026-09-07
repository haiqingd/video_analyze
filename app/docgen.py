"""生成最终攻略文档：Markdown（含截图与跳转链接）+ 服务端渲染 HTML。"""
from __future__ import annotations

import re
from pathlib import Path

import markdown as md_lib


def _link_timestamps(text: str, bvid: str, page: int) -> str:
    """把正文中**反引号包裹**的 `` `mm:ss` `` 时间戳替换为「引用式」跳转链接。

    正文只出现紧凑的 `[▶ 04:11][ts251]`，长 URL 统一放到文末定义区。
    只认反引号格式（提示词已要求 LLM 这样标注视频时间点），
    避免把"10:00睡觉"这类游戏内时刻误转成跳转链接。
    """
    defs: dict[str, str] = {}  # url -> label

    def make_ref(ts: str) -> str:
        parts = [int(p) for p in ts.split(":")]
        sec = (parts[0] * 3600 + parts[1] * 60 + parts[2]) if len(parts) == 3 else (parts[0] * 60 + parts[1])
        url = f"https://www.bilibili.com/video/{bvid}?p={page}&t={sec}"
        if url not in defs:
            defs[url] = f"ts{sec}"
        return f"[▶ {ts}][{defs[url]}]"

    body = re.sub(r"`([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)`", lambda m: make_ref(m.group(1)), text)
    if defs:
        block = "\n".join(f"[{label}]: {url}" for url, label in defs.items())
        body = f"{body}\n\n{block}\n"
    return body


_TS = re.compile(r"(?<![0-9:])([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)(?![0-9])")


def build_markdown(
    *,
    title: str,
    uploader: str,
    duration_sec: int,
    bvid: str,
    page: int,
    guide_md: str,
    cover_rel: str | None,
    shots: list[dict],
    subtitle_desc: str,
) -> str:
    """组装最终 Markdown 文档。shots: [{t, ts, caption, image(相对路径)}]"""
    dur = f"{duration_sec // 60}分{duration_sec % 60:02d}秒"
    lines = [
        f"# {title}",
        "",
        f"> UP主：**{uploader}** · 时长 {dur} · 字幕来源：{subtitle_desc} · "
        f"[在 B 站打开原视频](https://www.bilibili.com/video/{bvid}?p={page})",
        "",
    ]
    if cover_rel:
        lines += [f"![封面]({cover_rel})", ""]
    lines += [guide_md, ""]

    if shots:
        lines += ["## 关键画面", ""]
        for s in shots:
            lines += [f"### `{s['ts']}` · {s['caption']}", "", f"![{s['caption']}]({s['image']})", ""]

    lines += [
        "---",
        "*本文由 Video2Guide 自动生成：字幕 → AI 总结 → 关键帧截图，仅供参考。*",
    ]
    md = "\n".join(lines)
    return _link_timestamps(md, bvid, page)


def render_html(md_text: str, job_id: str) -> str:
    """Markdown → HTML（页面渲染版）。

    页面版去掉文末「关键画面」章节——前端有更好看的可交互卡片网格，
    避免 screenshots 渲染两遍；Markdown 文件本身保持完整。
    引用式链接的定义行（[tsN]: url）必须保留，否则时间戳跳转失效。
    """
    defs = re.findall(r"^\[(ts\d+)\]: (\S+)$", md_text, re.M)
    page_md = re.split(r"\n## 关键画面", md_text)[0]
    if defs:
        page_md += "\n\n" + "\n".join(f"[{name}]: {url}" for name, url in defs)
    html = md_lib.markdown(page_md, extensions=["tables", "nl2br", "sane_lists"])
    html = re.sub(r'src="(?!/|https?:)', f'src="/files/{job_id}/', html)
    # 图片懒加载
    html = html.replace("<img ", '<img loading="lazy" ')
    return html
