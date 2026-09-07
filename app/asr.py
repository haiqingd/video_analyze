"""本地语音识别兜底（faster-whisper，GPU 优先，CPU 回退）。

B 站 AI 字幕经常缺失/错配，此模块把音频流转成与字幕相同结构的 cues，
供下游总结流水线无缝使用。
"""
from __future__ import annotations

import threading
from pathlib import Path


class ASRError(Exception):
    pass


_model = None
_model_key: tuple = ()
# 可重入锁：解码异常时的 medium 回退会在锁内递归调用 transcribe_audio
_lock = threading.RLock()


def _get_model(size: str):
    global _model, _model_key
    if _model is not None and _model_key == (size,):
        return _model
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ASRError(
            "未安装 faster-whisper，无法使用本地语音识别：pip install faster-whisper"
        ) from e

    # Windows 下让 ctranslate2 找到 pip 安装的 CUDA 运行库
    _add_cuda_dll_dirs()

    # 优先使用本地模型目录（models/faster-whisper-*，规避 HF 下载不通）
    from .config import ROOT_DIR

    local_dir = ROOT_DIR / "models" / f"faster-whisper-{size}"
    model_path = str(local_dir) if (local_dir / "model.bin").exists() else size

    device, compute = "cpu", "int8"
    try:
        model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
        device = "cuda"
    except Exception:  # noqa: BLE001 — 无 CUDA/驱动不匹配时回退 CPU
        model = WhisperModel(model_path, device="cpu", compute_type="int8")
    _model, _model_key = model, (size,)
    return model


def _add_cuda_dll_dirs() -> None:
    import ctypes
    import os
    import site

    if os.name != "nt":
        return
    dirs = []
    for sp in set(site.getsitepackages() + [site.getusersitepackages()]):
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
            d = Path(sp) / sub
            if d.is_dir():
                dirs.append(d)
    if not dirs:
        return
    os.environ["PATH"] = os.pathsep.join(str(d) for d in dirs) + os.pathsep + os.environ.get("PATH", "")
    # 关键：按绝对路径预加载进本进程。之后 ctranslate2 按名字 LoadLibrary 时
    # 会直接命中已加载模块，绕开其依赖解析问题。
    for d in dirs:
        for dll in sorted(d.glob("*.dll")):
            try:
                ctypes.WinDLL(str(dll))
            except OSError:
                pass


def transcribe_audio(audio_path: Path, model_size: str = "medium", initial_prompt: str = "") -> list[dict]:
    """音频 → cues [{start, end, text}]，识别语言自动（中文视频会命中 zh）。

    initial_prompt：领域术语表（逗号分隔），引导解码器采用正确写法，
    能显著减少专有名词同音错字。
    """
    with _lock:
        model = _get_model(model_size)
        try:
            segments, info = model.transcribe(
                str(audio_path),
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                initial_prompt=initial_prompt or None,
            )
            cues = []
            for seg in segments:
                text = (seg.text or "").strip()
                if not text:
                    continue
                cues.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "Invalid token ID" in msg and model_size != "medium":
                # 词表边界 token 偶发触发解码错误：回退 medium 重识别
                cues = transcribe_audio(audio_path, model_size="medium", initial_prompt=initial_prompt)
                return cues
            raise ASRError(f"语音识别失败：{e}") from e
    return cues
