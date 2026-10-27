"""ffmpeg 위치, 영상 정보, 오디오 읽기."""
import os
import re
import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 16000


def ffmpeg() -> str:
    """동봉된 정적 ffmpeg(imageio-ffmpeg 패키지). 시스템 라이브러리에만 기대서 어느 맥에서나 돈다."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — 패키지가 없으면 시스템 ffmpeg
        for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if p and os.path.exists(p):
                return p
    raise RuntimeError("ffmpeg을 찾을 수 없습니다.")


def probe(path: str) -> dict:
    """길이와 영상·소리 트랙 유무. ffprobe 없이 `ffmpeg -i` 출력을 읽는다."""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise ValueError("영상 길이를 읽을 수 없습니다. 지원하지 않는 파일일 수 있습니다.")
    h, mi, sec = m.groups()
    streams = [line for line in err.splitlines() if "Stream #" in line]
    return {
        "duration": int(h) * 3600 + int(mi) * 60 + float(sec),
        "has_video": any("Video:" in line and "attached pic" not in line for line in streams),
        "has_audio": any("Audio:" in line for line in streams),
    }


def load_audio(path: str, sr: int = SAMPLE_RATE) -> np.ndarray:
    """모노 float32 PCM으로 디코딩."""
    out = subprocess.run(
        [ffmpeg(), "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, np.float32).copy()


def peaks(audio: np.ndarray, sr: int = SAMPLE_RATE, per_sec: int = 100) -> list[float]:
    """파형 표시용 구간별 최대 진폭(0~1)."""
    step = sr // per_sec
    n = len(audio) // step
    if n == 0:
        return []
    chunk = np.abs(audio[: n * step]).reshape(n, step).max(axis=1)
    top = float(chunk.max()) or 1.0
    return np.round(chunk / top, 3).tolist()
