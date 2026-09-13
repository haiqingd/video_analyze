"""任务流水线：字幕 → GLM 总结 →（并行）视频下载 → 截图 → 文档。"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import asr, bilibili, docgen, frames, llm as llm_mod, reference
from .config import OUTPUT_DIR, settings

STEPS = [
    ("meta", "解析视频信息"),
    ("subtitle", "获取字幕/语音识别"),
    ("llm", "AI 总结"),
    ("frames", "下载视频并截图"),
    ("doc", "生成文档"),
]

# ---- ASR 辅助：术语表构建 + LLM 同音字纠错 ----
def _asr_terms(job: "Job", meta: bilibili.VideoMeta | None = None) -> str:
    """ASR initial_prompt / 纠错术语表：视频与合集标题中的关键词 + 参考文档高频词。

    不再内置任何游戏的固定词表（避免星露谷词条干扰其他游戏的转写）；
    视频/合集标题天然包含游戏名与专有名词，参考文档则提供该攻略的高频术语。
    """
    import re as _re
    from collections import Counter

    parts: list[str] = []
    if meta:
        for name in (meta.season_title, meta.title, meta.uploader):
            for w in _re.split(r"[·|｜:：!！?？\-—\s，,、/（）()]+", name):
                if len(w) >= 2 and w not in parts:
                    parts.append(w)
    if job.reference_url:
        try:
            ref = reference.fetch_tencent_doc(job.reference_url)
            words = _re.findall(r"[一-鿿]{2,4}", ref)
            cnt = Counter(words)
            for w, c in cnt.most_common(300):
                if c < 4 or len(parts) >= 60:
                    break
                if any(w in e or e in w for e in parts):
                    continue
                parts.append(w)
        except reference.ReferenceError:
            pass
    return "，".join(parts)[:400]


def _llm_correct(client, cues: list, job: "Job") -> list:
    """用 LLM 修正转写稿中的同音错别字（只改字，不改写）。"""
    from .llm import LLMError

    CH = 150  # 每块 cue 数
    for start in range(0, len(cues), CH):
        chunk = cues[start : start + CH]
        numbered = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(chunk, 1))
        tpl = (ROOT_PROMPTS / "correct.md").read_text(encoding="utf-8")
        system = tpl.replace("{TERMS}", _asr_terms(job)).replace("{TEXT}", numbered)
        try:
            out = client.chat("你是一名字幕校对员，严格遵守系统规则。", system)
        except LLMError as e:
            job.log(f"⚠ 同音字纠错失败（块 {start // CH + 1}），保留原稿：{str(e)[:50]}")
            continue
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        parsed = []
        for ln in lines:
            m = re.match(r"^(\d+)[.、]\s*(.+)$", ln)
            if m:
                parsed.append(m.group(2).strip())
        if len(parsed) == len(chunk):
            for c, fixed in zip(chunk, parsed):
                c["text"] = fixed
        else:
            job.log(f"⚠ 纠错块 {start // CH + 1} 行数不匹配（{len(parsed)}/{len(chunk)}），保留原稿")
    job.log("同音字纠错完成")
    return cues


SUBTITLE_CACHE = OUTPUT_DIR / "cache" / "subtitles"
SUBTITLE_CACHE.mkdir(parents=True, exist_ok=True)
ROOT_PROMPTS = OUTPUT_DIR.parent / "prompts"


def _cache_path(bvid: str, cid: int) -> Path:
    return SUBTITLE_CACHE / f"{bvid}_{cid}.json"


def _load_cached_cues(bvid: str, cid: int) -> dict | None:
    p = _cache_path(bvid, cid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_cached_cues(bvid: str, cid: int, source: str, cues: list[dict]) -> None:
    try:
        _cache_path(bvid, cid).write_text(
            json.dumps({"source": source, "cues": cues}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


@dataclass
class Job:
    id: str
    url: str
    style: str = "standard"
    shot_count: int = 6
    reference_url: str = ""
    sessdata: str = ""
    api_key: str = ""
    model: str = ""
    status: str = "queued"  # queued | running | done | error
    step: str = "meta"
    error: str = ""
    logs: list[dict] = field(default_factory=list)
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def dir(self) -> Path:
        return OUTPUT_DIR / self.id

    def log(self, msg: str) -> None:
        self.logs.append(
            {"t": datetime.now().strftime("%H:%M:%S"), "msg": msg, "step": self.step}
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._dl_pool = ThreadPoolExecutor(max_workers=1)  # 视频下载独立排队，避免占用主流程
        self._load_persisted()

    def _load_persisted(self) -> None:
        """启动时回载历史任务（output/*/job.json），重启后页面历史不丢。"""
        for p in sorted(OUTPUT_DIR.glob("*/job.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                job = Job(
                    id=data["id"], url=data.get("url", ""), style=data.get("style", "standard"),
                    shot_count=data.get("shot_count", 0), status=data.get("status", "done"),
                    error=data.get("error", ""), created_at=data.get("created_at", ""),
                    result=data.get("result"),
                )
                if job.status in ("running", "queued"):
                    job.status, job.error = "error", "服务重启导致任务中断，请重新提交"
                self._jobs[job.id] = job
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    def _persist(self, job: Job) -> None:
        try:
            job.dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "id": job.id, "url": job.url, "style": job.style, "shot_count": job.shot_count,
                "reference_url": job.reference_url,
                "status": job.status, "error": job.error, "created_at": job.created_at,
                "result": job.result,
            }
            (job.dir / "job.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def create(self, **kwargs) -> Job:
        job = Job(id=datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6], **kwargs)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def register(self, job: Job) -> None:
        """注册一个外部构建的任务（导入 .v2g 用）。"""
        with self._lock:
            self._jobs[job.id] = job

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    # ------------------------------------------------------------------
    def _run(self, job: Job) -> None:
        job.status = "running"
        try:
            result = run_pipeline(job)
            job.result = result
            job.status = "done"
            job.log("完成 ✔")
        except bilibili.BilibiliError as e:
            job.status, job.error = "error", str(e)
        except asr.ASRError as e:
            job.status, job.error = "error", str(e)
        except llm_mod.LLMError as e:
            job.status, job.error = "error", str(e)
        except frames.FramesError as e:
            # 截图只是增强项：失败降级为无图文档
            job.log(f"⚠ {e}")
            if job.result is None:
                job.status, job.error = "error", str(e)
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "error", f"未预期的错误：{e.__class__.__name__}: {e}"
        finally:
            self._persist(job)


def run_pipeline(job: Job) -> dict[str, Any]:
    sessdata = job.sessdata or settings.bilibili_sessdata

    # ---- 1. 视频元信息 -------------------------------------------------
    job.step = "meta"
    job.log("解析链接与视频信息…")
    bvid, page = bilibili.parse_url(job.url)
    meta = bilibili.get_video_meta(bvid, page, sessdata)
    job.log(f"《{meta.title}》UP主 {meta.uploader}，时长 {meta.duration // 60} 分钟")
    if len(meta.pages) > 1:
        job.log(f"该视频共 {len(meta.pages)} 个分P，当前处理 P{page}")

    job.dir.mkdir(parents=True, exist_ok=True)

    # ---- 2. 字幕（缓存 → B站字幕逐轨校验 → 本地语音识别兜底） -----------
    job.step = "subtitle"
    cues: list[dict] = []
    desc = ""
    coverage_warn = ""

    cached = _load_cached_cues(bvid, meta.cid)
    if cached and cached.get("cues"):
        cues, desc = cached["cues"], cached["source"]
        job.log(f"使用本地缓存字幕（{desc}，{len(cues)} 条）")
    else:
        job.log("获取字幕轨道…")
        tracks = bilibili.list_subtitle_tracks(bvid, meta.cid, sessdata)
        # 按优先级逐轨下载并做健康度检查（B站 AI 字幕偶发整轨错配/残缺）
        ranked = sorted(
            [t for t in tracks],
            key=lambda t: (0 if "zh" in t.lan.lower() else 1, 1 if t.is_ai else 0),
        )
        for t in ranked:
            try:
                cand = bilibili.fetch_subtitle_cues(t)
            except Exception as e:  # noqa: BLE001 — 单轨失败换下一轨
                job.log(f"⚠ 字幕轨 {t.lan_doc} 下载失败：{e}")
                continue
            if bilibili.cues_look_sane(cand, meta.duration):
                cues = cand
                desc = ("AI 智能字幕" if t.is_ai else "CC 字幕") + f"（{t.lan_doc}）"
                job.log(f"使用{desc}（{len(cues)} 条，校验通过）")
                _save_cached_cues(bvid, meta.cid, desc, cues)
                break
            covered = max((c["end"] for c in cand), default=0)
            job.log(
                f"⚠ 字幕轨 {t.lan_doc} 不可用（{len(cand)} 条，仅覆盖 {int(covered)}s / 全长 {meta.duration}s，疑似错配或残缺），换下一轨"
            )

    if not cues:
        # 本地语音识别兜底：下载音频 → faster-whisper 转写
        job.log("B 站字幕不可用，启用本地语音识别（faster-whisper）…")
        audio_path = job.dir / "audio.m4a"
        try:
            if not audio_path.exists():
                frames.download_audio(job.url, audio_path)
                job.log(f"音频下载完成（{audio_path.stat().st_size // 1024 // 1024} MB）")
            job.log("语音识别中（GPU 优先，约需几分钟）…")
            cues = asr.transcribe_audio(audio_path, model_size=settings.asr_model, initial_prompt=_asr_terms(job, meta))
            if settings.asr_correct:
                _asr_client = llm_mod.GLMClient(settings.zhipu_api_key or job.api_key, settings.glm_model, settings.glm_base_url)
                cues = _llm_correct(_asr_client, cues, job)
            if not cues:
                raise asr.ASRError("识别结果为空")
            desc = f"本地语音识别（faster-whisper {settings.asr_model}）"
            _save_cached_cues(bvid, meta.cid, desc, cues)
            job.log(f"语音识别完成：{len(cues)} 条")
        finally:
            try:
                audio_path.unlink(missing_ok=True)
            except OSError:
                pass

    if not cues:
        raise bilibili.BilibiliError(
            "既没有可用的 B 站字幕，本地语音识别也失败了，无法总结该视频。"
        )

    # 覆盖率体检：字幕明显短于视频时提醒用户
    covered = max(c["end"] for c in cues)
    if covered < meta.duration * 0.5:
        coverage_warn = (
            f"⚠ 字幕仅覆盖视频前 {int(covered // 60)} 分钟（全长 {meta.duration // 60} 分钟），"
            "疑似 B 站字幕缺失或错配，以下总结可能不完整甚至与视频无关，请留意核对。"
        )
        job.log("⚠ " + coverage_warn[2:])
    subtitle_cache = job.dir / "subtitle_raw.json"
    subtitle_cache.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    total_chars = sum(len(c["text"]) for c in cues)
    job.log(f"字幕共 {len(cues)} 条 / {total_chars} 字")

    # ---- 3. 截图准备：视频下载与 AI 总结并行 ---------------------------
    # 视频文件走全局缓存（跨任务复用，减少重复下载与风控概率）
    want_shots = max(0, job.shot_count)
    dl_future = None
    VIDEO_CACHE = OUTPUT_DIR / "cache" / "videos"
    VIDEO_CACHE.mkdir(parents=True, exist_ok=True)
    video_path = VIDEO_CACHE / f"{bvid}_p{page}.mp4"
    if want_shots > 0 and not video_path.exists():
        def _download() -> Path:
            job.log("后台下载视频流（用于截图）…")
            p = frames.download_video(job.url, video_path)
            job.log(f"视频下载完成（{p.stat().st_size // 1024 // 1024} MB）")
            return p

        dl_future = job_manager._dl_pool.submit(_download)

    # ---- 4. AI 总结 ----------------------------------------------------
    job.step = "llm"
    # 服务端 Key 优先（客户端传的 Key 仅在服务端未配置时生效，避免浏览器里的过期 Key 拖垮任务）
    api_key = settings.zhipu_api_key or job.api_key
    model = job.model or settings.glm_model
    client = llm_mod.GLMClient(api_key, model, settings.glm_base_url)
    final_client = llm_mod.GLMClient(api_key, settings.glm_final_model, settings.glm_base_url)
    job.log(f"调用 {model} 抽取与笔记，{final_client.model} 合成攻略…")
    # 参考文档：每次解析实时重新拉取（短 TTL 缓存防批量连击）
    ref_text = ""
    if job.reference_url:
        try:
            ref_text = reference.fetch_tencent_doc(job.reference_url)
            job.log(f"已载入参考文档（{len(ref_text)} 字，实时抓取）")
        except reference.ReferenceError as e:
            job.log(f"⚠ 参考文档载入失败，本次不注入：{e}")

    guide_md = llm_mod.summarize_transcript(
        client, meta.title, meta.uploader, meta.duration, cues, style=job.style,
        log=job.log, final_client=final_client, reference=ref_text,
    )
    (job.dir / "guide_body.md").write_text(guide_md, encoding="utf-8")
    job.log("攻略生成完毕")

    # ---- 5. 截图 -------------------------------------------------------
    shots: list[dict] = []
    if want_shots > 0:
        job.step = "frames"
        try:
            if dl_future is not None:
                dl_future.result(timeout=900)
            if video_path.exists():
                moments = llm_mod.extract_key_moments(guide_md, meta.duration, limit=want_shots)
                job.log(f"按攻略时间点截图：{len(moments)} 张")
                img_dir = job.dir / "images"
                imgs = frames.grab_frames(video_path, [m["t"] for m in moments], img_dir)
                for m, img in zip(moments, imgs):
                    shots.append({**m, "image": f"images/{img.name}"})
                # 视频留在缓存目录供复用，不再删除
            else:
                job.log("⚠ 未下载到视频，跳过截图")
        except Exception as e:  # noqa: BLE001 — 截图是增强项，失败降级为无图文档
            job.log(f"⚠ 截图失败，文档将不含图片：{e}")
            shots = []

    # ---- 6. 文档 -------------------------------------------------------
    job.step = "doc"
    job.log("组装最终文档…")
    cover = frames.download_cover(meta.cover_url, job.dir / "images" / "cover.jpg")
    cover_rel = "images/cover.jpg" if cover else None
    final_md = docgen.build_markdown(
        title=meta.title,
        uploader=meta.uploader,
        duration_sec=meta.duration,
        bvid=bvid,
        page=page,
        guide_md=guide_md,
        cover_rel=cover_rel,
        shots=shots,
        subtitle_desc=desc,
    )
    (job.dir / "guide.md").write_text(final_md, encoding="utf-8")
    html = docgen.render_html(final_md, job.id)
    (job.dir / "guide.html").write_text(html, encoding="utf-8")

    job.log("文档已生成：guide.md / guide.html")
    return {
        "video": {
            "bvid": bvid,
            "page": page,
            "title": meta.title,
            "uploader": meta.uploader,
            "duration": meta.duration,
            "pubdate": meta.pubdate,
            "season_id": meta.season_id,
            "season_title": meta.season_title,
            "url": f"https://www.bilibili.com/video/{bvid}?p={page}",
            "cover": f"/files/{job.id}/images/cover.jpg" if cover else "",
            "pages": len(meta.pages),
        },
        "subtitle_desc": desc,
        "coverage_warn": coverage_warn,
        "guide_md": final_md,
        "guide_html": html,
        "shots": [
            {
                **s,
                "image": f"/files/{job.id}/{s['image']}",
                "jump": f"https://www.bilibili.com/video/{bvid}?p={page}&t={s['t']}",
            }
            for s in shots
        ],
        "files": {
            "markdown": f"/files/{job.id}/guide.md",
            "html": f"/files/{job.id}/guide.html",
        },
        "model": f"{model} + {final_client.model}",
    }


job_manager = JobManager()
