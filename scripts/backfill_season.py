"""一次性回填：为历史任务补全 B 站合集（ugc_season）信息。

背景：早期生成的任务 job.json 没有记录视频所属合集（season_id / season_title），
前端历史列表因此无法按合集分组。本脚本查询每个 BV 的合集归属并写回 job.json。

- 合集映射缓存在 output/cache/seasons.json（bv → {"id", "title"}）；
  查询一个 BV 会顺带缓存它所在合集的**全部成员**，因此 66 集的系列只需 1 次请求。
- 不属于任何合集的视频记为 {"id": 0, "title": ""}，同样进缓存，避免重复查询。
- 幂等可续跑：已有 season 字段的任务跳过；每查完一个 BV 就落盘缓存。

用法：
    python scripts/backfill_season.py                                        # 宿主机（需 httpx）
    docker compose exec -T video2guide python - < scripts/backfill_season.py # 容器内
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))
except NameError:
    # 经 stdin 执行（python - < 脚本）时没有 __file__，容器 WORKDIR 即项目根
    ROOT = Path.cwd()

from app import bilibili  # noqa: E402
from app.config import OUTPUT_DIR, settings  # noqa: E402

CACHE_FILE = OUTPUT_DIR / "cache" / "seasons.json"


def load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def season_roster(view_data: dict) -> tuple[dict, list[str]]:
    """从 view 接口响应提取合集信息与全部成员 BV。"""
    season = view_data.get("ugc_season") or {}
    info = {"id": int(season.get("id") or 0), "title": str(season.get("title") or "")}
    bvids: list[str] = []
    if info["id"]:
        for sec in season.get("sections", []):
            for ep in sec.get("episodes", []):
                if ep.get("bvid"):
                    bvids.append(ep["bvid"])
    return info, bvids


def main() -> None:
    cache = load_cache()
    known: dict = cache.setdefault("bv", {})  # bv -> {"id","title"}

    # 1. 收集需要回填的任务（result.video 有 bvid 但还没有 season 字段）
    todo: list[tuple[Path, dict]] = []
    need_query: list[str] = []
    for p in sorted(OUTPUT_DIR.glob("*/job.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"跳过无法解析的 {p}")
            continue
        video = ((data.get("result") or {}).get("video") or {})
        bv = video.get("bvid")
        if not bv or "season_id" in video:
            continue
        todo.append((p, data))
        if bv not in known and bv not in need_query:
            need_query.append(bv)

    print(f"待回填任务 {len(todo)} 个，需查询 BV {len(need_query)} 个", flush=True)

    # 2. 查询合集归属（一个 BV 的响应包含整个合集的成员列表）
    if need_query:
        client = bilibili._make_client(settings.bilibili_sessdata)
        try:
            for i, bv in enumerate(need_query, 1):
                if bv in known:  # 已被之前合集的成员列表覆盖
                    continue
                info, roster = {"id": 0, "title": ""}, []
                for attempt in range(4):
                    r = client.get(bilibili.API + "/x/web-interface/view", params={"bvid": bv})
                    if r.status_code == 412 and attempt < 3:
                        wait = 30 * (attempt + 1)
                        print(f"  ⚠ {bv} 触发 B 站风控(412)，等 {wait}s 重试", flush=True)
                        time.sleep(wait)
                        continue
                    if r.status_code != 200:
                        raise SystemExit(f"{bv} 查询失败 HTTP {r.status_code}，进度已保存，稍后重跑续跑")
                    data = r.json()
                    if data.get("code") != 0:
                        print(f"  ⚠ {bv} 接口报错：{data.get('message')}，按无合集处理", flush=True)
                        break
                    info, roster = season_roster(data["data"])
                    break
                else:
                    raise SystemExit(f"{bv} 连续被风控，进度已保存，稍后重跑本脚本续跑")
                known[bv] = info
                for member in roster:
                    known.setdefault(member, info)
                save_cache(cache)
                label = f"『{info['title']}』共 {len(roster)} 集" if info["id"] else "无合集"
                print(f"[{i}/{len(need_query)}] {bv} → {label}", flush=True)
                time.sleep(0.6)
        finally:
            client.close()

    # 3. 写回 job.json（临时文件 + 原子替换，避免写一半损坏）
    updated = 0
    counts: dict[str, int] = {}
    for p, data in todo:
        video = data["result"]["video"]
        info = known.get(video["bvid"])
        if info is None:
            continue  # 查询未完成，留给下次重跑
        video["season_id"] = int(info.get("id") or 0)
        video["season_title"] = str(info.get("title") or "")
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        updated += 1
        name = info.get("title") or "（无合集）"
        counts[name] = counts.get(name, 0) + 1

    print(f"\n回填完成：更新 {updated} / {len(todo)} 个任务", flush=True)
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name}: {n} 个")
    if updated < len(todo):
        print("有任务未查到合集信息（查询失败），可重跑本脚本续跑")


if __name__ == "__main__":
    main()
