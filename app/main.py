"""FastAPI 服务：REST 接口 + 静态前端 + 产物文件服务。"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import OUTPUT_DIR, ROOT_DIR, settings
from .jobs import STEPS, Job, job_manager

app = FastAPI(title="Video2Guide", docs_url=None, redoc_url=None)


class ExtractRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    style: str = "standard"
    shot_count: int = 6
    sessdata: str = ""
    api_key: str = ""
    model: str = ""
    access_key: str = ""
    reference_url: str = ""


@app.get("/api/config")
def get_config() -> dict:
    return {
        "has_server_key": bool(settings.zhipu_api_key),
        "has_server_sessdata": bool(settings.bilibili_sessdata),
        "model": settings.glm_model,
        "base_url": settings.glm_base_url,
    }


@app.post("/api/extract")
def extract(req: ExtractRequest) -> dict:
    if not req.access_key or req.access_key != settings.access_key:
        raise HTTPException(403, "访问密钥不正确，请联系 462574808@qq.com 获取密钥")
    if not req.api_key and not settings.zhipu_api_key:
        raise HTTPException(400, "未配置 GLM API Key：请在右上角「设置」中填写，或写入 .env 的 ZHIPU_API_KEY")
    job = job_manager.create(
        url=req.url.strip(),
        style=req.style if req.style in ("brief", "standard", "detailed") else "standard",
        shot_count=max(0, min(12, req.shot_count)),
        sessdata=req.sessdata.strip(),
        api_key=req.api_key.strip(),
        model=req.model.strip(),
        reference_url=req.reference_url.strip(),
    )
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或服务已重启")
    step_keys = [k for k, _ in STEPS]
    cur = step_keys.index(job.step) if job.step in step_keys else 0
    steps = []
    for i, (k, label) in enumerate(STEPS):
        if job.status == "done" or i < cur:
            state = "done"
        elif i == cur and job.status == "running":
            state = "active"
        elif i == cur and job.status == "error":
            state = "error"
        else:
            state = "pending"
        steps.append({"key": k, "label": label, "state": state})
    data = {
        "id": job.id,
        "status": job.status,
        "step": job.step,
        "steps": steps,
        "logs": job.logs[-80:],
        "error": job.error,
        "created_at": job.created_at,
        "result": job.result,
    }
    return data


# ---------------- 评论（匿名，随任务目录持久化） ----------------
class CommentRequest(BaseModel):
    name: str = Field(default="", max_length=30)
    text: str = Field(max_length=600)


def _comments_path(job_id: str) -> Path:
    # 防路径穿越：job_id 只允许字母数字下划线
    if not job_id.replace("_", "").isalnum():
        raise HTTPException(400, "非法任务 ID")
    return OUTPUT_DIR / job_id / "comments.json"


@app.get("/api/jobs/{job_id}/comments")
def get_comments(job_id: str) -> dict:
    p = _comments_path(job_id)
    if not p.exists():
        return {"comments": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = []
    return {"comments": data[-100:]}


@app.post("/api/jobs/{job_id}/comments")
def add_comment(job_id: str, req: CommentRequest) -> dict:
    if not (OUTPUT_DIR / job_id).exists():
        raise HTTPException(404, "任务不存在")
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "评论内容不能为空")
    name = req.name.strip() or "匿名"
    p = _comments_path(job_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = []
    data.append(
        {
            "id": len(data) + 1,
            "name": name,
            "text": text,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )
    p.write_text(json.dumps(data[-200:], ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "comments": data[-100:]}


@app.get("/api/jobs")
def list_jobs() -> dict:    return {
        "jobs": [
            {"id": j.id, "status": j.status, "created_at": j.created_at,
             "title": (j.result or {}).get("video", {}).get("title", j.url),
             "url": j.url,
             "cover": (j.result or {}).get("video", {}).get("cover", ""),
             "duration": (j.result or {}).get("video", {}).get("duration", 0),
             "bvid": (j.result or {}).get("video", {}).get("bvid", ""),
             "pubdate": (j.result or {}).get("video", {}).get("pubdate", 0)}
            for j in job_manager.all()[:200]
        ]
    }


# ---------------- 导出 / 导入（.v2g = zip：job.json + 文档 + 图片 + 评论） ----------------
@app.get("/api/jobs/{job_id}/export")
def export_job(job_id: str):
    job = job_manager.get(job_id)
    if job is None or not (OUTPUT_DIR / job_id).exists():
        raise HTTPException(404, "任务不存在")
    d = OUTPUT_DIR / job_id
    title = ((job.result or {}).get("video") or {}).get("title", "guide")[:30]
    safe_title = re.sub(r"[\\/:*?\"<>|\s]+", "_", title)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.name != "_cookies.txt":
                zf.write(p, p.relative_to(d).as_posix())
    from urllib.parse import quote

    from fastapi.responses import Response

    return Response(
        content=buf.getvalue(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{safe_title}-{job_id}.v2g')}"},
    )


@app.post("/api/jobs/import")
async def import_job(file: UploadFile) -> dict:
    raw = await file.read()
    if len(raw) > 60 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>60MB）")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是有效的 .v2g 导出文件")
    names = zf.namelist()
    # 定位 job.json（根目录或唯一子目录）
    meta_name = next((n for n in names if n.endswith("job.json") and n.count("/") <= 1), None)
    if not meta_name:
        raise HTTPException(400, "导出文件缺少 job.json")
    prefix = meta_name.rsplit("job.json", 1)[0]
    try:
        meta = json.loads(zf.read(meta_name).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "job.json 解析失败")
    if not ((meta.get("result") or {}).get("video") or {}).get("bvid"):
        raise HTTPException(400, "job.json 内容不完整（缺少视频信息）")

    # ID 冲突时换新 ID（import_ 前缀 + 时间戳）
    new_id = meta.get("id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", new_id or "") or (OUTPUT_DIR / new_id).exists():
        new_id = "import_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    meta["id"] = new_id
    if meta.get("result"):
        meta["result"]["files"] = {
            "markdown": f"/files/{new_id}/guide.md",
            "html": f"/files/{new_id}/guide.html",
        }
        for s in meta["result"].get("shots", []):
            img = s.get("image", "")
            s["image"] = f"/files/{new_id}/{img.split('/', 3)[-1] if img.startswith('/files/') else img}"
        cover = meta["result"].get("video", {}).get("cover", "")
        if cover.startswith("/files/"):
            meta["result"]["video"]["cover"] = f"/files/{new_id}/{cover.split('/', 3)[-1]}"

    dest = OUTPUT_DIR / new_id
    dest.mkdir(parents=True, exist_ok=True)
    for n in names:
        if not n.startswith(prefix) or n == meta_name or n.endswith("/"):
            continue
        rel = n[len(prefix):]
        if ".." in rel or rel.startswith("/") or rel.startswith("_"):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(n))
    (dest / "job.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    job = Job(
        id=new_id, url=meta.get("url", ""), status="done",
        created_at=meta.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        result=meta.get("result"),
    )
    job_manager.register(job)
    title = ((job.result or {}).get("video") or {}).get("title", "")
    return {"ok": True, "job_id": new_id, "title": title}


# 产物文件（output/{job_id}/...）与静态前端
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/files", StaticFiles(directory=OUTPUT_DIR), name="files")
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "static" / "index.html")
