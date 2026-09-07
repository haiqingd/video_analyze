"""批量跑完整个 115 攻略系列（断点续跑：已有成品的集自动跳过）。

进度写入 output/batch_progress.txt，重跑本脚本可续跑/补漏。
"""
import json
import time
from pathlib import Path

from app import bilibili
from app.config import OUTPUT_DIR
from app.jobs import job_manager

PROGRESS_FILE = OUTPUT_DIR / "batch_progress.txt"
# 参考文档（UP主文字版攻略，每次任务实时拉取最新内容）
REFERENCE_URL = "https://docs.qq.com/doc/DSVBkcWpRb2NxYWxq"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---- 1. 拉全集列表 ----
client = bilibili._make_client()
try:
    r = client.get(bilibili.API + "/x/web-interface/view", params={"bvid": "BV1LeMU6XEJL"})
    season = (r.json()["data"].get("ugc_season") or {})
finally:
    client.close()
eps: list[tuple[str, str]] = []
for sec in season.get("sections", []):
    for ep in sec.get("episodes", []):
        if ep["bvid"] not in [b for b, _ in eps]:
            eps.append((ep["bvid"], ep["title"]))
log(f"系列共 {len(eps)} 集")

# ---- 2. 断点：跳过已用当前一代提示词生成的视频（该时刻之后完成的视为最新版） ----
CURRENT_GEN_SINCE = "2026-09-06 17:00"
done: set[str] = set()
for p in OUTPUT_DIR.glob("*/job.json"):
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("status") == "done" and data.get("created_at", "") >= CURRENT_GEN_SINCE:
            bv = ((data.get("result") or {}).get("video") or {}).get("bvid")
            if bv:
                done.add(bv)
    except (json.JSONDecodeError, OSError):
        continue
log(f"已是最新版 {len(done)} 集，跳过")

# ---- 3. 提交其余 ----
todo = [(bv, t) for bv, t in eps if bv not in done]
submitted = []
for i, (bv, title) in enumerate(todo, 1):
    j = job_manager.create(url=f"https://www.bilibili.com/video/{bv}", style="standard", shot_count=6, reference_url=REFERENCE_URL)
    submitted.append((j.id, bv, title))
log(f"已提交 {len(submitted)} 集，开始处理（预计数小时）")

# ---- 4. 监控 ----
t0 = time.time()
ids = {jid for jid, _, _ in submitted}
error_jobs: list[tuple[str, str, str]] = []
last_report = 0.0
while ids and time.time() - t0 < 8 * 3600:
    time.sleep(30)
    now_done, running = [], []
    for jid, bv, title in submitted:
        if jid not in ids:
            continue
        job = job_manager.get(jid)
        if job.status == "done":
            ids.discard(jid)
            now_done.append(title[:18])
        elif job.status == "error":
            ids.discard(jid)
            error_jobs.append((bv, title[:18], job.error[:60]))
    # 每 5 分钟或全部结束时输出汇总
    if now_done or time.time() - last_report > 300 or not ids:
        cur = []
        for jid, bv, title in submitted:
            if jid in ids:
                job = job_manager.get(jid)
                step = job.step if job else "?"
                cur.append(f"{title[:10]}({step})")
        log(
            f"进度 {len(submitted) - len(ids)}/{len(submitted)} | 剩 {len(ids)} | "
            f"错误 {len(error_jobs)} | 当前: {', '.join(cur[:3])} | 用时 {int(time.time()-t0)//60}min"
        )
        last_report = time.time()

log("=== 批量完成 ===")
log(f"成功 {len(submitted) - len(error_jobs)} / 失败 {len(error_jobs)}")
for bv, title, err in error_jobs:
    log(f"  失败: {title} ({bv}) - {err}")
log("失败的集可重跑本脚本自动补漏")
