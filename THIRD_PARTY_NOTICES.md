# 제3자 구성 요소 / Third-party components

JUMPCUT 코드는 MIT 라이선스입니다. 배포하는 앱(.app/.dmg)에는 아래 구성 요소가 함께 들어갑니다.

| 구성 요소 | 용도 | 라이선스 | 출처 |
|---|---|---|---|
| FFmpeg 7.1 (imageio-ffmpeg 패키지의 정적 빌드) | 영상 디코딩·인코딩 | **GPL v2+** (libx264 포함 빌드) | https://ffmpeg.org · https://github.com/imageio/imageio-ffmpeg |
| Whisper large-v3-turbo (실행 중 내려받음) | 받아쓰기 | MIT | https://github.com/openai/whisper |
| mlx / mlx-whisper | Apple Silicon 받아쓰기 엔진 | MIT | https://github.com/ml-explore/mlx-examples |
| YAMNet (ONNX 변환본) | 기침·재채기 같은 소리 분류 | Apache 2.0 | https://github.com/tensorflow/models/tree/master/research/audioset/yamnet |
| ONNX Runtime | YAMNet 실행 | MIT | https://github.com/microsoft/onnxruntime |
| wavesurfer.js 7.12.12 | 파형·타임라인 | BSD-3-Clause | https://github.com/katspaugh/wavesurfer.js |
| pywebview | 앱 창 | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| FastAPI, Uvicorn | 앱 내부 서버 | MIT, BSD-3-Clause | https://fastapi.tiangolo.com |

FFmpeg은 별도 프로그램으로 동봉되어 JUMPCUT이 명령줄로 실행합니다. FFmpeg 소스 코드는 위 FFmpeg 사이트에서 받을 수 있고, 동봉 빌드의 구성은 imageio-ffmpeg 저장소에 공개되어 있습니다.
