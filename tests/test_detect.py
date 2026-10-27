"""모델 없이 돌아가는 컷 계산 테스트."""
import numpy as np

from jumpcut import detect


def w(word, start, end):
    return {"word": word, "start": start, "end": end, "prob": 1.0}


def test_keeps_is_duration_minus_merged_cuts():
    cuts = [
        {"start": 1.0, "end": 2.0, "enabled": True},
        {"start": 1.5, "end": 3.0, "enabled": True},   # 겹치면 합친다
        {"start": 5.0, "end": 6.0, "enabled": False},  # 꺼진 컷은 무시
    ]
    assert detect.merge(cuts, 10) == [(1.0, 3.0)]
    assert detect.keeps(cuts, 10) == [(0.0, 1.0), (3.0, 10)]


def test_repeat_cuts_first_attempt():
    words = [w("제가", 0.0, 0.3), w("요즘", 0.3, 0.6), w("쓰는,", 0.6, 0.9),
             w("제가", 1.1, 1.4), w("요즘", 1.4, 1.7), w("쓰는", 1.7, 2.0), w("카메라를", 2.0, 2.5)]
    cuts = detect._repeats(words)
    assert len(cuts) == 1
    assert (cuts[0]["start"], cuts[0]["end"]) == (0.0, 1.1)


def test_no_repeat_for_different_sentences():
    words = [w("저는", 0, .3), w("사과를", .3, .7), w("좋아해요.", .7, 1.2), w("저는", 1.5, 1.8), w("배를", 1.8, 2.1), w("싫어해요.", 2.1, 2.6)]
    assert detect._repeats(words) == []


def test_silence_found_between_tones():
    sr = 16000
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr).astype(np.float32)
    audio = np.concatenate([tone, np.zeros(sr * 2, np.float32) + 1e-4, tone])
    spans = detect.silences(audio, detect.DEFAULTS)
    assert len(spans) == 1
    a, b = spans[0]
    assert abs(a - 1.0) < 0.05 and abs(b - 3.0) < 0.05


def test_filler_detection_strong_and_weak():
    segs = [{"words": [w("음,", 0.0, 0.4), w("그", 1.0, 1.2), w("사람이", 1.25, 1.6), w("그", 2.2, 2.4), w("왔어요", 2.8, 3.2)]}]
    audio = np.zeros(16000 * 4, np.float32)
    cuts = detect.detect(audio, segs, 4.0, {"noises": False, "repeats": False})
    fillers = [(c["start"], c["end"]) for c in cuts if c["type"] == "filler"]
    # “음”은 항상, 두 번째 “그”는 앞뒤로 쉼이 있어서 군말. “그 사람이”의 “그”는 진짜 말
    assert fillers == [(0.0, 0.4), (2.2, 2.4)]
