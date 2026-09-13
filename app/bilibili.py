"""Bilibili 接口层：视频元信息、WBI 签名、字幕获取。

字幕获取流程：
  1. GET /x/web-interface/view        → 拿 cid / 标题 / 分P 列表（无需登录）
  2. GET /x/web-interface/nav         → 拿 WBI 签名用的 img_key / sub_key
  3. GET /x/player/wbi/v2 (WBI签名)    → 拿字幕列表（AI 字幕需要 SESSDATA 登录态）
  4. GET subtitle_url                  → 字幕 JSON（body: [{from,to,content}]）
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from .config import UA

API = "https://api.bilibili.com"

# WBI mixin key 混淆表（社区公开的固定表）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


class BilibiliError(Exception):
    """带用户可读信息的 B 站接口错误。"""


@dataclass
class VideoMeta:
    bvid: str
    cid: int
    page: int
    title: str
    uploader: str
    duration: int  # 秒
    cover_url: str
    pubdate: int = 0  # 发布时间戳（秒），用于系列排序
    season_id: int = 0  # 所属合集（ugc_season）ID，0 = 不属于任何合集
    season_title: str = ""  # 合集标题（如"115攻略"）
    pages: list[dict[str, Any]] = None  # type: ignore[assignment]


def _make_client(sessdata: str = "") -> httpx.Client:
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    client = httpx.Client(headers=headers, timeout=20, follow_redirects=True)
    if sessdata:
        client.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")
    # 先访问主页拿 buvid 等基础 Cookie，降低风控概率
    try:
        client.get("https://www.bilibili.com/")
    except httpx.HTTPError:
        pass
    return client


def _wbi_keys(client: httpx.Client) -> tuple[str, str]:
    r = client.get(f"{API}/x/web-interface/nav")
    data = r.json().get("data") or {}
    wbi = data.get("wbi_img") or {}
    img_url: str = wbi.get("img_url", "")
    sub_url: str = wbi.get("sub_url", "")
    if not img_url or not sub_url:
        raise BilibiliError("无法获取 WBI 签名参数（接口返回异常）")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def _wbi_sign(params: dict[str, Any], img_key: str, sub_key: str) -> dict[str, Any]:
    mixin_key = "".join((img_key + sub_key)[i] for i in _MIXIN_KEY_ENC_TAB)[:32]
    params = dict(sorted({k: str(v) for k, v in params.items()}.items()))
    params["wts"] = str(int(time.time()))
    cleaned = {
        k: "".join(ch for ch in str(v) if ch not in "!'()*")
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(cleaned)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)
_P_RE = re.compile(r"[?&]p=(\d+)")


def parse_url(url: str) -> tuple[str, int]:
    """从任意 B 站链接（含 b23.tv 短链）解析出 (bvid, page)。"""
    url = url.strip()
    if not url:
        raise BilibiliError("请输入视频链接")
    if "b23.tv" in url or url.startswith("http") and "BV" not in url and "av" not in url.lower():
        # 短链：跟随重定向拿真实地址
        try:
            r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
            url = str(r.url)
        except httpx.HTTPError as e:
            raise BilibiliError(f"短链解析失败：{e}") from e
    m = _BV_RE.search(url)
    if m:
        bvid = m.group(1)
    else:
        m = _AV_RE.search(url)
        if not m:
            raise BilibiliError("未在链接中找到 BV 号，请粘贴完整的视频地址")
        r = httpx.get(
            f"{API}/x/web-interface/view",
            params={"aid": m.group(1)},
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            timeout=15,
        )
        bvid = (r.json().get("data") or {}).get("bvid")
        if not bvid:
            raise BilibiliError("av 号解析失败，请直接使用 BV 链接")
    page = 1
    pm = _P_RE.search(url)
    if pm:
        page = max(1, int(pm.group(1)))
    return bvid, page


def _fetch_view(bvid: str, sessdata: str = "") -> dict[str, Any]:
    """请求 view 接口并返回 data（校验 code）。"""
    client = _make_client(sessdata)
    try:
        r = client.get(f"{API}/x/web-interface/view", params={"bvid": bvid})
        data = r.json()
    finally:
        client.close()
    if data.get("code") != 0:
        raise BilibiliError(f"获取视频信息失败：{data.get('message', '未知错误')}")
    return data["data"]


def get_video_meta(bvid: str, page: int = 1, sessdata: str = "") -> VideoMeta:
    v = _fetch_view(bvid, sessdata)
    pages = v.get("pages", [])
    if pages:
        page = min(page, len(pages))
        cid = pages[page - 1]["cid"]
        title = pages[page - 1].get("part") or v["title"]
        duration = pages[page - 1].get("duration") or v["duration"]
    else:
        cid, title, duration = v["cid"], v["title"], v["duration"]
    season = v.get("ugc_season") or {}
    return VideoMeta(
        bvid=bvid,
        cid=cid,
        page=page,
        title=title,
        uploader=v["owner"]["name"],
        duration=int(duration),
        cover_url=v.get("pic", ""),
        pubdate=int(v.get("pubdate") or 0),
        season_id=int(season.get("id") or 0),
        season_title=str(season.get("title") or ""),
        pages=[{"page": p["page"], "part": p["part"], "duration": p["duration"]} for p in pages],
    )


def get_season(bvid: str, sessdata: str = "") -> dict[str, Any] | None:
    """查询 BV 所属的 UGC 合集；不属于任何合集时返回 None。

    返回 {"id": int, "title": str, "uploader": str,
          "episodes": [{"bvid","title","duration","pubdate","cover"}, ...]}（按合集内顺序）。
    """
    v = _fetch_view(bvid, sessdata)
    season = v.get("ugc_season") or {}
    if not season.get("id"):
        return None
    episodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sec in season.get("sections", []):
        for ep in sec.get("episodes", []):
            bv = ep.get("bvid")
            if not bv or bv in seen:
                continue
            seen.add(bv)
            episodes.append(
                {
                    "bvid": bv,
                    "title": str(ep.get("title") or ""),
                    "duration": int(ep.get("duration") or 0),
                    "pubdate": int(ep.get("pubdate") or 0),
                    "cover": str(ep.get("cover") or ""),
                }
            )
    return {
        "id": int(season["id"]),
        "title": str(season.get("title") or ""),
        "uploader": v["owner"]["name"],
        "episodes": episodes,
    }


@dataclass
class SubtitleTrack:
    lan: str
    lan_doc: str
    ai_type: int  # 接口的 ai_type（实测 AI 字幕也可能为 0，不可靠）
    url: str

    @property
    def is_ai(self) -> bool:
        # 实测 AI 字幕的 lan 形如 "ai-zh"
        return self.lan.startswith("ai") or "ai" in self.lan_doc.lower()


def list_subtitle_tracks(bvid: str, cid: int, sessdata: str = "") -> list[SubtitleTrack]:
    """列出可用字幕轨道。AI 智能字幕必须带 SESSDATA 登录态才会返回。

    先走 WBI 签名接口（网页播放器同款），失败或为空再退回旧接口兜底。
    """
    client = _make_client(sessdata)
    try:
        subs: list[dict] = []
        try:
            img_key, sub_key = _wbi_keys(client)
            params = _wbi_sign(
                {"bvid": bvid, "cid": cid, "fnval": 4048, "fnver": 0, "qn": 64},
                img_key,
                sub_key,
            )
            r = client.get(f"{API}/x/player/wbi/v2", params=params)
            data = r.json()
            if data.get("code") == 0:
                subs = ((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
        except (httpx.HTTPError, BilibiliError):
            pass
        if not subs:
            # 兜底：旧版非 WBI 接口
            r = client.get(f"{API}/x/player/v2", params={"bvid": bvid, "cid": cid})
            data = r.json()
            if data.get("code") != 0:
                raise BilibiliError(f"获取字幕列表失败：{data.get('message', '未知错误')}")
            subs = ((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    finally:
        client.close()
    tracks = []
    for s in subs:
        url = s.get("subtitle_url") or ""
        if url.startswith("//"):
            url = "https:" + url
        if not url:
            continue
        tracks.append(
            SubtitleTrack(
                lan=s.get("lan", ""),
                lan_doc=s.get("lan_doc", s.get("lan", "")),
                ai_type=int(s.get("ai_type", 0) or 0),
                url=url,
            )
        )
    return tracks


def pick_track(tracks: list[SubtitleTrack]) -> SubtitleTrack | None:
    """优先级：中文人工CC > 中文AI > 其他人工 > 其他AI。"""
    if not tracks:
        return None

    def rank(t: SubtitleTrack) -> tuple[int, int]:
        is_zh = "zh" in t.lan.lower()
        return (0 if is_zh else 1, 1 if t.is_ai else 0)

    return sorted(tracks, key=rank)[0]


def cues_look_sane(cues: list[dict[str, Any]], duration_sec: int) -> bool:
    """字幕健康度检查：条数足够且覆盖过半。

    B 站 AI 字幕存在整轨错配（内容属于其他视频）或只生成开头一小段的情况，
    覆盖率是目前最可靠的机器可判信号。
    """
    if len(cues) < 30:
        return False
    covered = max((c["end"] for c in cues), default=0)
    return covered >= duration_sec * 0.5


def fetch_subtitle_cues(track: SubtitleTrack) -> list[dict[str, Any]]:
    """下载字幕 JSON，返回 [{start, end, text}]。"""
    r = httpx.get(
        track.url,
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    cues = []
    for item in data.get("body", []):
        text = (item.get("content") or "").strip()
        if not text:
            continue
        cues.append(
            {
                "start": float(item.get("from", 0)),
                "end": float(item.get("to", 0)),
                "text": text,
            }
        )
    return cues
