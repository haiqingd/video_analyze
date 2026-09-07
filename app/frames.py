"""视频下载（yt-dlp）+ 指定时间点截图（OpenCV，不依赖 ffmpeg）。"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import UA

# 全局下载互斥：B 站对并发抓取非常敏感（412 风控），同一时刻只跑一个 yt-dlp
_dl_mutex = threading.Lock()
_BACKOFFS = (0, 20, 60, 120, 180)


def _run_download(cmd: list[str], dest: Path, what: str) -> Path:
    with _dl_mutex:
        for attempt, backoff in enumerate(_BACKOFFS, 1):
            if backoff:
                time.sleep(backoff)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
            if proc.returncode == 0 and dest.exists():
                return dest
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise FramesError(f"{what}失败（已重试 {len(_BACKOFFS)} 次）：" + " | ".join(tail))


class FramesError(Exception):
    pass


def _warm_cookies_file(dest: Path) -> Path:
    """访问 B 站主页获取 buvid 等基础 Cookie，写成 Netscape 格式给 yt-dlp 用（规避 412 风控）。"""
    import httpx

    jar_path = dest.parent / "_cookies.txt"
    try:
        client = httpx.Client(
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            timeout=15, follow_redirects=True,
        )
        try:
            client.get("https://www.bilibili.com/")
        finally:
            client.close()
        lines = ["# Netscape HTTP Cookie File"]
        for c in client.cookies.jar:
            domain = c.domain or ".bilibili.com"
            if not domain.startswith("."):
                domain = "." + domain
            expiry = int(c.expires or (time.time() + 86400 * 30))
            secure = "TRUE" if c.has_nonstandard_attr("secure") or domain.endswith("bilibili.com") else "FALSE"
            lines.append(f"{domain}\tTRUE\t{c.path or '/'}\t{secure}\t{expiry}\t{c.name}\t{c.value}")
        jar_path.write_text("\n".join(lines), encoding="utf-8")
    except httpx.HTTPError:
        return jar_path  # 写不出来就算了，裸下
    return jar_path


def download_video(url: str, dest: Path, max_height: int = 720) -> Path:
    """下载一条视频流（不含音轨，无需 ffmpeg 合并）。失败抛 FramesError。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fmt = (
        f"bv*[height<={max_height}][ext=mp4]/bv*[height<={max_height}]/"
        f"b[vcodec!=none][height<={max_height}]/b[vcodec!=none]"
    )
    jar = _warm_cookies_file(dest)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", fmt,
        "--no-playlist",
        "--no-part",
        "--retries", "3",
        "--sleep-requests", "1",
        "--socket-timeout", "20",
        "--user-agent", UA,
        "--referer", "https://www.bilibili.com/",
        "--cookies", str(jar),
        "-o", str(dest),
        url,
    ]
    return _run_download(cmd, dest, "视频下载")


def download_audio(url: str, dest: Path) -> Path:
    """下载音频流（语音识别用，m4a，无需 ffmpeg）。失败抛 FramesError。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    jar = _warm_cookies_file(dest)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "ba[ext=m4a]/ba/bestaudio",
        "--no-playlist",
        "--no-part",
        "--retries", "3",
        "--sleep-requests", "1",
        "--socket-timeout", "20",
        "--user-agent", UA,
        "--referer", "https://www.bilibili.com/",
        "--cookies", str(jar),
        "-o", str(dest),
        url,
    ]
    return _run_download(cmd, dest, "音频下载")


def grab_frames(video: Path, timestamps: list[float], out_dir: Path, width: int = 960) -> list[Path]:
    """在指定时间点（秒）截取帧，返回成功生成的图片路径列表。"""
    try:
        import cv2
    except ImportError as e:
        raise FramesError("未安装 opencv-python-headless，无法截图") from e
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FramesError(f"无法打开视频文件：{video.name}")
    paths: list[Path] = []
    try:
        for i, t in enumerate(timestamps, 1):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                # 个别位置读不到（结尾附近），跳过该帧
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
            p = out_dir / f"shot_{i:02d}_{int(t)}s.jpg"
            cv2.imwrite(str(p), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            paths.append(p)
    finally:
        cap.release()
    return paths


def download_cover(url: str, dest: Path) -> Path | None:
    """下载封面图（本地化，避免文档外链失效）。"""
    import httpx

    if not url:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.get(
            url if url.startswith("http") else "https:" + url,
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            timeout=30,
            follow_redirects=True,
        )
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            return dest
    except httpx.HTTPError:
        pass
    return None
