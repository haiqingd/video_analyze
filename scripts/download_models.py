"""下载 faster-whisper 模型到 models/（国内走 ModelScope 镜像）。

用法：
    python scripts/download_models.py            # 下载默认模型（large-v3-turbo + medium）
    python scripts/download_models.py turbo      # 只下载 turbo
    python scripts/download_models.py medium     # 只下载 medium

说明：
- turbo 镜像缺 vocabulary.txt（接口返回错误 JSON），本脚本会从 medium 词表复制，
  个别音频可能触发词表边界 token 解码错误——程序已内置自动回退 medium 的兜底。
"""
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

REPOS = {
    "turbo": ("faster-whisper-large-v3-turbo", "large-v3-turbo"),
    "medium": ("faster-whisper-medium", "medium"),
}
FILES = ["config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
BASE = "https://modelscope.cn/models/Pengzhendong/{}/resolve/master/{}"


def download(name: str) -> None:
    repo, dirname = REPOS[name]
    dest = MODELS / f"faster-whisper-{dirname}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = dest / f
        if target.exists() and target.stat().st_size > 1000 and f != "vocabulary.txt":
            print(f"  已存在: {f}")
            continue
        url = BASE.format(repo, f)
        print(f"  下载 {f} …")
        try:
            urllib.request.urlretrieve(url, target)
        except urllib.error.HTTPError as e:
            # turbo 镜像缺 vocabulary.txt 时直接 404，跳过、稍后从 medium 词表复制
            if f == "vocabulary.txt" and e.code == 404:
                print(f"  {f} 镜像缺失（404），稍后从 medium 词表复制")
                continue
            # medium 镜像缺 preprocessor_config.json；faster-whisper 会回退默认特征参数，不影响使用
            if f == "preprocessor_config.json" and e.code == 404:
                print(f"  {f} 镜像缺失（404），跳过（faster-whisper 用默认参数）")
                continue
            raise SystemExit(f"下载失败：{f}（HTTP {e.code}）")
        # ModelScope 缺文件时返回 JSON 错误而不是 404，识别并处理
        # （注意 *.json 本身就以 { 开头，只对非 JSON 文件做此检查）
        if not f.endswith(".json") and target.read_bytes()[:1] == b"{":
            if f == "vocabulary.txt":
                target.unlink(missing_ok=True)
                print(f"  {f} 镜像缺失，稍后从 medium 词表复制")
            else:
                target.unlink(missing_ok=True)
                raise SystemExit(f"下载失败：{f}")
    print(f"完成: {dest.name}")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("turbo", "all"):
        print("[turbo = large-v3-turbo，速度与质量兼顾]")
        download("turbo")
    if which in ("medium", "all"):
        print("[medium，CPU 场景 / 回退用]")
        download("medium")
    # turbo 词表修复：从 medium 复制（同一套多语言词表）
    turbo_vocab = MODELS / "faster-whisper-large-v3-turbo" / "vocabulary.txt"
    medium_vocab = MODELS / "faster-whisper-medium" / "vocabulary.txt"
    if medium_vocab.exists() and not (turbo_vocab.exists() and turbo_vocab.stat().st_size > 10000):
        shutil.copy(medium_vocab, turbo_vocab)
        print("已复制 medium 词表到 turbo（修复镜像缺失）")


if __name__ == "__main__":
    main()
