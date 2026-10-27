"""컷 후보 찾기: 무음, 군말, 반복(NG 테이크), 기침 같은 잡음."""
import csv
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import numpy as np

from .media import SAMPLE_RATE

DEFAULTS = {
    "min_silence": 0.5,   # 이보다 긴 무음만 자름(초)
    "keep_pad": 0.15,     # 자른 자리 양옆에 남길 숨(초)
    "sensitivity": 0.3,   # 0=바닥 소음에 붙임, 1=말소리에 붙임. 높을수록 작은 소리도 무음으로 봄
    "fillers": True,
    "repeats": True,
    "noises": True,
    "noise_score": 0.3,   # 잡음 판정 기준(0~1). 낮출수록 더 많이 잡음
}

# YAMNet 클래스 → 화면에 보일 이름. 말이 아닌 몸 소리만 고른다(숨소리 자체는 자연스러워서 뺌)
NOISES = {
    # 기침·재채기·콧소리·숨 들이켬은 모델이 서로 헷갈려서 한 이름으로 묶는다
    "Cough": "기침·재채기", "Sneeze": "기침·재채기", "Snort": "기침·재채기", "Gasp": "기침·재채기",
    "Throat clearing": "헛기침", "Sniff": "코 훌쩍임", "Burping, eructation": "트림", "Hiccup": "딸꾹질",
}
MODELS = Path(__file__).parent / "models"
YAMNET_HOP, YAMNET_WIN = 0.48, 0.96

# 항상 군말로 보는 것
STRONG = re.compile(r"^(음+|어+|으+|엄+|흠+|에+|으음|어어|음음)$")
# 앞뒤로 쉼이 있을 때만 군말로 보는 것(평소엔 진짜 단어)
WEAK = {"아", "그", "저", "뭐", "이제", "막", "약간", "그러니까", "그니까", "뭐랄까", "저기", "그래서", "근데"}
PUNCT = re.compile(r"[\s.,?!…~·\-\"'“”‘’()]+")


def _norm(text: str) -> str:
    return PUNCT.sub("", text)


def frame_db(audio: np.ndarray, hop: float = 0.01) -> np.ndarray:
    n = int(SAMPLE_RATE * hop)
    m = len(audio) // n
    if m == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(audio[: m * n].reshape(m, n) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def _threshold(db: np.ndarray, p: dict) -> float:
    floor, speech = np.percentile(db, 10), np.percentile(db, 90)
    return floor + p["sensitivity"] * (speech - floor)


def silences(audio: np.ndarray, p: dict, hop: float = 0.01) -> list[tuple[float, float]]:
    db = frame_db(audio, hop)
    if len(db) == 0:
        return []
    quiet = db < _threshold(db, p)
    out, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            a, b = start * hop, i * hop
            if b - a >= p["min_silence"]:
                out.append((a, b))
            start = None
    return out


@lru_cache(maxsize=1)
def _yamnet():
    import onnxruntime as ort

    sess = ort.InferenceSession(str(MODELS / "yamnet.onnx"), providers=["CPUExecutionProvider"])
    names = [row[2] for row in list(csv.reader(open(MODELS / "yamnet_class_map.csv")))[1:]]
    return sess, names


def noises(audio: np.ndarray, p: dict) -> list[dict]:
    """기침·재채기 등. YAMNet은 0.48초 간격으로 0.96초 창을 보므로, 창 안에서 실제 소리가 난 부분으로 좁힌다."""
    sess, names = _yamnet()
    scores = sess.run(None, {sess.get_inputs()[0].name: audio.astype(np.float32)})[0]
    ids = {names.index(n): label for n, label in NOISES.items() if n in names}
    speech = names.index("Speech")
    db = frame_db(audio)
    thr = _threshold(db, p)
    out = []
    for f, row in enumerate(scores):
        j = max(ids, key=lambda i: row[i])
        if row[j] < p["noise_score"] or row[speech] > 0.5:
            continue
        a = f * YAMNET_HOP
        loud = np.where(db[int(a * 100): int((a + YAMNET_WIN) * 100)] >= thr)[0]
        if not len(loud):
            continue
        s, e = a + loud[0] / 100 - 0.05, a + (loud[-1] + 1) / 100 + 0.05
        if out and s <= out[-1]["end"]:   # 겹치는 창은 하나로
            out[-1]["end"] = max(out[-1]["end"], e)
            continue
        out.append({"start": s, "end": e, "type": "noise", "reason": f"{ids[j]} 소리"})
    return out


def _words(segments):
    return [w for s in segments for w in s["words"]]


def _repeats(words, max_k=6):
    """단어 k개 묶음이 바로 뒤에서 거의 똑같이 다시 나오면 앞쪽(첫 시도)을 자른다.
    “제가 요즘 쓰는, 제가 요즘 쓰는 카메라” → 앞의 “제가 요즘 쓰는,”"""
    idx = [i for i, w in enumerate(words) if not STRONG.match(_norm(w["word"]))]  # 군말은 건너뛰고 비교
    norms = [_norm(words[i]["word"]) for i in idx]
    out, j = [], 0
    while j < len(idx):
        hit = 0
        for k in range(min(max_k, (len(idx) - j) // 2), 0, -1):
            a, b = "".join(norms[j:j + k]), "".join(norms[j + k:j + 2 * k])
            if len(a) >= 2 and SequenceMatcher(None, a, b).ratio() >= 0.85:
                hit = k
                break
        if hit:
            first, nxt = words[idx[j]], words[idx[j + hit]]
            said = " ".join(words[i]["word"] for i in idx[j:j + hit])
            out.append({"start": first["start"], "end": nxt["start"], "type": "repeat", "reason": f"다시 말함 “{said}”"})
            j += hit
        else:
            j += 1
    return out


def detect(audio: np.ndarray, segments: list[dict], duration: float, params: dict | None = None) -> list[dict]:
    p = {**DEFAULTS, **(params or {})}
    pad = p["keep_pad"]
    cuts = []

    for a, b in silences(audio, p):
        s = 0.0 if a <= 0.01 else a + pad   # 맨 앞·맨 뒤 무음은 여유 없이 자름
        e = duration if b >= duration - 0.02 else b - pad
        if e - s >= 0.05:
            cuts.append({"start": s, "end": e, "type": "silence", "reason": f"무음 {b - a:.1f}초"})

    words = _words(segments)
    if p["fillers"]:
        for i, w in enumerate(words):
            t = _norm(w["word"])
            prev_gap = w["start"] - words[i - 1]["end"] if i else 9
            next_gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 9
            if STRONG.match(t) or (t in WEAK and prev_gap >= 0.2 and next_gap >= 0.2):
                cuts.append({"start": w["start"], "end": w["end"], "type": "filler", "reason": f"군말 “{t}”"})

    if p["repeats"]:
        cuts += _repeats(words)

    if p["noises"]:
        cuts += noises(audio, p)

    cuts.sort(key=lambda c: c["start"])
    for i, c in enumerate(cuts):
        c.update(id=f"ai-{i}", source="ai", enabled=True,
                 start=round(max(c["start"], 0), 3), end=round(min(c["end"], duration), 3))
    return cuts


def merge(cuts: list[dict], duration: float) -> list[tuple[float, float]]:
    """켜진 컷들을 합친 구간 목록."""
    spans = sorted((max(c["start"], 0), min(c["end"], duration)) for c in cuts if c.get("enabled", True))
    out: list[list[float]] = []
    for a, b in spans:
        if b - a < 0.02:
            continue
        if out and a <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def keeps(cuts: list[dict], duration: float) -> list[tuple[float, float]]:
    """살릴 구간 = 전체 - 컷."""
    out, t = [], 0.0
    for a, b in merge(cuts, duration):
        if a - t >= 0.04:
            out.append((t, a))
        t = b
    if duration - t >= 0.04:
        out.append((t, duration))
    return out
