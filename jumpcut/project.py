"""영상 하나의 분석 결과와 편집 상태. 원본 옆 `<이름>.jumpcut.json`에 저장한다."""
import json
import time
from functools import lru_cache
from pathlib import Path

from . import detect, media, transcribe

VERSION = 1


def project_path(src: str) -> Path:
    p = Path(src)
    return p.with_name(p.name + ".jumpcut.json")


def load(src: str) -> dict | None:
    pp = project_path(src)
    if not pp.exists():
        return None
    data = json.loads(pp.read_text())
    st = Path(src).stat()
    if data.get("source_mtime") != st.st_mtime or data.get("source_size") != st.st_size:
        return None  # 원본이 바뀌었으면 새로 분석
    return data


def save(data: dict) -> None:
    data["saved_at"] = time.time()
    project_path(data["source"]).write_text(json.dumps(data, ensure_ascii=False, indent=1))


def analyze(src: str, language: str | None = "ko", on_progress=None) -> dict:
    src = str(Path(src).resolve())
    info = media.probe(src)
    if not info["has_audio"]:
        raise ValueError("소리가 없는 파일입니다.")
    step = on_progress or (lambda stage, frac: None)
    step("audio", 0)
    audio = _audio(src, Path(src).stat().st_mtime)
    step("model", 0)
    model = transcribe.ensure_model(lambda f: step("model", f))
    step("transcribe", 0)
    segments = transcribe.transcribe(audio, language, lambda f: step("transcribe", f), model)
    step("detect", 0)
    st = Path(src).stat()
    data = {
        "version": VERSION,
        "source": src,
        "source_mtime": st.st_mtime,
        "source_size": st.st_size,
        **info,
        "language": language,
        "segments": segments,
        "peaks": media.peaks(audio),
        "params": dict(detect.DEFAULTS),
        "cuts": detect.detect(audio, segments, info["duration"]),
    }
    save(data)
    return data


@lru_cache(maxsize=1)  # 마지막 영상 하나만 들고 있는다. 원본이 바뀌면 mtime이 달라져 새로 읽는다
def _audio(src: str, mtime: float):
    return media.load_audio(src)


def redetect(data: dict, params: dict) -> dict:
    """감도만 바꿔 AI 컷을 다시 계산. 받아쓰기는 재사용하고, 직접 만든 컷은 그대로 둔다.
    사용자가 꺼 둔 AI 컷과 같은 자리의 새 컷은 꺼진 채로 둔다."""
    data["params"] = {**data["params"], **params}
    off = {(c["type"], c["start"], c["end"]) for c in data["cuts"] if c.get("source") == "ai" and not c["enabled"]}
    ai = detect.detect(_audio(data["source"], data["source_mtime"]), data["segments"], data["duration"], data["params"])
    for c in ai:
        if (c["type"], c["start"], c["end"]) in off:
            c["enabled"] = False
    data["cuts"] = ai + [c for c in data["cuts"] if c.get("source") == "user"]
    save(data)
    return data
