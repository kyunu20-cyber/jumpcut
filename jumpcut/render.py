"""살릴 구간만 이어 붙여 내보내기.

원본을 한 번만 디코딩하면서 select/aselect로 컷 구간을 버리고, 버린 시간만큼 타임스탬프를 당긴다.
프레임레이트가 일정하지 않은 영상(아이폰 등)도 싱크가 맞고, 구간 수가 많아도 메모리가 늘지 않는다.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .detect import keeps
from .media import ffmpeg, probe

FADE = 0.01  # 이음새 오디오 페이드(초)


def _removed_expr(cuts: list[tuple[float, float]]) -> str:
    """원본 시각 T 이전에 잘려 나간 시간의 합."""
    return "+".join(f"clip(T-{a:.4f},0,{b - a:.4f})" for a, b in cuts) or "0"


def _keep_expr(spans: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.4f},{b:.4f})" for a, b in spans) or "0"


def _envelope(spans: list[tuple[float, float]]) -> str:
    """구간 경계마다 FADE 길이로 0→1, 1→0. 각 구간 안쪽에서만 계산."""
    terms = [f"between(t,{a:.4f},{b:.4f})*min(min((t-{a:.4f})/{FADE},({b:.4f}-t)/{FADE}),1)" for a, b in spans]
    return "+".join(terms) or "0"


def _encoder() -> list[str]:
    encoders = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" in encoders:
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    return ["-c:v", "h264_videotoolbox", "-q:v", "70", "-pix_fmt", "yuv420p"]


def render(src: str, out: str, cuts: list[dict], on_progress: Callable[[float], None] | None = None) -> str:
    info = probe(src)
    dur = info["duration"]
    spans = keeps(cuts, dur)
    if not spans:
        raise ValueError("남는 구간이 없습니다.")
    # 지울 구간은 살릴 구간의 여집합. keeps()가 버린 아주 짧은 조각까지 함께 당겨야 이음새에 빈 시간이 안 생긴다
    edges = [0.0, *[x for s in spans for x in s], dur]
    removed = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2) if edges[i + 1] > edges[i]]
    new_dur = sum(b - a for a, b in spans)
    keep, shift = _keep_expr(spans), f"PTS-({_removed_expr(removed)})/TB"

    chains = []
    if info["has_video"]:
        chains.append(f"[0:v:0]select='{keep}',setpts='{shift}'[v]")
    if info["has_audio"]:
        chains.append(
            "[0:a:0]asetnsamples=n=64,"
            f"volume=eval=frame:volume='{_envelope(spans)}',"
            f"aselect='{keep}',asetpts='{shift}',"
            "aresample=async=1:first_pts=0[a]"
        )

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(";\n".join(chains))
        script = f.name

    cmd = [ffmpeg(), "-y", "-nostdin", "-v", "error", "-i", src, "-/filter_complex", script]
    if info["has_video"]:
        cmd += ["-map", "[v]", *_encoder()]
    if info["has_audio"]:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", out]

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryFile("w+") as err:   # stderr는 파일로 받아 파이프가 차서 멈추는 일을 막는다
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
            for line in proc.stdout:
                if line.startswith("out_time_us=") and on_progress and new_dur:
                    try:
                        on_progress(min(int(line.split("=")[1]) / 1e6 / new_dur, 1.0))
                    except ValueError:
                        pass
            if proc.wait() != 0:
                err.seek(0)
                raise RuntimeError(f"ffmpeg 실패: {err.read()[-800:]}")
    finally:
        Path(script).unlink(missing_ok=True)
    return out
