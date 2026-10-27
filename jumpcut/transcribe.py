"""단어 단위 타임스탬프 받아쓰기(mlx-whisper). Apple Silicon 전용."""
import os
import platform
import threading
from pathlib import Path
from typing import Callable

import numpy as np


# 군말을 지우지 않고 받아 적도록 유도하는 프롬프트
FILLER_PROMPT = "음, 어, 그, 아, 저기, 음... 그러니까, 어... 뭐랄까, 이제 그"

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
UNSUPPORTED = "JUMPCUT은 Apple Silicon(M1 이후) 맥에서만 동작합니다. Intel 맥은 지원하지 않습니다."

Progress = Callable[[float], None]


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def require_apple_silicon():
    """Intel 맥(Rosetta 포함)에서는 바로 끝낸다."""
    if not is_apple_silicon():
        raise SystemExit(UNSUPPORTED)


def ensure_model(on_progress: Progress | None = None) -> str:
    """모델을 받아 두고 로컬 경로를 돌려준다. 이미 있으면 바로 돌려준다.
    huggingface_hub는 바이트 단위 진행률을 콜백으로 주지 않아서, 받는 동안 캐시 폴더 크기를 잰다."""
    from huggingface_hub import HfApi, snapshot_download

    repo = MLX_MODEL
    try:
        return snapshot_download(repo, local_files_only=True)
    except Exception:  # noqa: BLE001 — 아직 없음
        pass
    total = sum(s.size or 0 for s in HfApi().model_info(repo, files_metadata=True).siblings) or 1
    cache = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub")) / f"models--{repo.replace('/', '--')}"
    done = threading.Event()

    def watch():
        while not done.wait(0.5):
            size = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file() and not f.is_symlink()) if cache.exists() else 0
            if on_progress:
                on_progress(min(size / total, 0.99))

    threading.Thread(target=watch, daemon=True).start()
    try:
        return snapshot_download(repo)
    finally:
        done.set()


def transcribe(audio: np.ndarray, language: str | None = "ko", on_progress: Progress | None = None,
               model: str | None = None) -> list[dict]:
    """[{text, start, end, words: [{word, start, end, prob}]}] 형태의 문장 목록."""
    require_apple_silicon()
    model = model or ensure_model()
    import importlib

    import tqdm as real_tqdm

    # 패키지 __init__이 같은 이름의 함수를 내보내서 모듈은 importlib로 꺼낸다
    mt = importlib.import_module("mlx_whisper.transcribe")

    class _Bar(real_tqdm.tqdm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **{**kw, "disable": False, "file": open(os.devnull, "w")})

        def update(self, n=1):
            super().update(n)
            if on_progress and self.total:
                on_progress(min(self.n / self.total, 1.0))

    class _Shim:  # mlx_whisper 내부의 tqdm.tqdm 만 바꿔 끼운다
        tqdm = _Bar

    orig = mt.tqdm
    mt.tqdm = _Shim
    try:
        result = mt.transcribe(
            audio, path_or_hf_repo=model, language=language, word_timestamps=True,
            initial_prompt=FILLER_PROMPT, condition_on_previous_text=False, verbose=False,
        )
    finally:
        mt.tqdm = orig
    return [_segment(s["text"], s["start"], s["end"], s.get("words", [])) for s in result["segments"]]


def _segment(text, start, end, words):
    return {
        "text": text.strip(),
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "words": [
            {"word": w["word"].strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
             "prob": round(float(w.get("probability", 1.0)), 3)}
            for w in words if w["word"].strip()
        ],
    }
