"""jumpcut 영상.mp4 [-o 출력.mp4] — 분석해서 바로 잘린 영상을 만든다. 검토 화면은 `jumpcut-app`."""
import argparse
import sys
from pathlib import Path

from . import project, render
from .detect import merge
from .transcribe import require_apple_silicon


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jumpcut", description="말 사이 무음·군말·반복을 자동으로 잘라냅니다.")
    ap.add_argument("video")
    ap.add_argument("-o", "--output")
    ap.add_argument("--lang", default="ko", help="언어 코드(ko, en, ja...). auto면 자동 감지")
    ap.add_argument("--min-silence", type=float)
    ap.add_argument("--no-fillers", action="store_true")
    ap.add_argument("--no-repeats", action="store_true")
    ap.add_argument("--reanalyze", action="store_true", help="저장된 분석을 무시하고 새로 받아쓰기")
    ap.add_argument("--dry-run", action="store_true", help="컷 목록만 출력")
    a = ap.parse_args(argv)
    require_apple_silicon()

    src = str(Path(a.video).resolve())
    lang = None if a.lang == "auto" else a.lang
    data = None if a.reanalyze else project.load(src)
    if data and data.get("language") != lang:
        data = None   # 다른 언어로 해 둔 분석은 쓰지 않는다
    if data is None:
        last = [""]

        def progress(stage, frac):
            label = {"audio": "오디오 읽는 중", "model": "모델 내려받는 중", "transcribe": "받아쓰는 중", "detect": "컷 찾는 중"}[stage]
            line = f"\r{label} {frac * 100:5.1f}%"
            if line != last[0]:
                sys.stderr.write(line)
                last[0] = line

        data = project.analyze(src, lang, progress)
        sys.stderr.write("\n")

    params = {}
    if a.min_silence is not None:
        params["min_silence"] = a.min_silence
    if a.no_fillers:
        params["fillers"] = False
    if a.no_repeats:
        params["repeats"] = False
    if params:
        data = project.redetect(data, params)

    on = [c for c in data["cuts"] if c["enabled"]]
    for c in on:
        print(f"{c['start']:8.2f} ~ {c['end']:8.2f}  {c['type']:8s} {c['reason']}")
    removed = sum(b - a for a, b in merge(on, data["duration"]))
    print(f"\n컷 {len(on)}개, {removed:.1f}초 제거 → {data['duration']:.1f}초 중 {data['duration'] - removed:.1f}초 남음")
    if a.dry_run:
        return

    p = Path(src)
    out = a.output or str(Path.home() / "Movies" / "JUMPCUT" / f"{p.stem}_cut.mp4")
    render.render(src, out, data["cuts"], lambda f: sys.stderr.write(f"\r내보내는 중 {f * 100:5.1f}%"))
    sys.stderr.write("\n")
    print(out)


if __name__ == "__main__":
    main()
