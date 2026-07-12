# silence-removal

녹화·녹음 파일(영상+오디오)의 무음 구간을 짧게 줄여 정리하는 CLI 도구.

## 요구사항
- Python 3.10+
- ffmpeg, ffprobe (PATH에 등록)
  - Windows: `winget install Gyan.FFmpeg`

## 설치
```bash
pip install -e .
```

## 사용법
```bash
silence-removal recording.mp4               # 파일 하나
silence-removal ./recordings                # 폴더 일괄
silence-removal talk.mp4 --keep-silence 0.5  # 무음 0.5초 남김
silence-removal talk.mp4 --copy              # 빠른 무손실 모드
silence-removal ./videos --dry-run --json    # 예상 결과만(에이전트용)
```

## 주요 옵션
| 옵션 | 설명 | 기본 |
|------|------|------|
| `--threshold DB` | 무음 기준 dB | -30 |
| `--min-silence SEC` | 이 길이 이상만 무음 처리 | 0.5 |
| `--keep-silence SEC` | 잘라낸 무음에 남길 총 길이(앞뒤 절반씩) | 0.3 |
| `--copy` | 무손실 스트림복사(빠름, 싱크 미세오차 감수) | precise |
| `--dry-run` | 처리 없이 예상 결과만 | - |
| `--json` | stdout에 JSON 출력 | - |
| `-o, --output DIR` | 출력 폴더 (기본: 원본 옆 `*_trimmed`) | - |
| `-y, --yes` | 덮어쓰기 확인 생략 | - |

## 모드
- **precise (기본)**: 재인코딩. A/V 싱크 100% 보장, 하드웨어 인코더(NVENC/QSV/AMF) 자동 사용(품질 고정), 없으면 libx264(CRF 18).
- **copy (`--copy`)**: 스트림 복사. 무손실·초고속. 단, 컷이 **키프레임 단위**로만 일어나 잘리는 위치가 정확하지 않고(무음이 조금 더 남을 수 있음), 컷이 많으면 미세한 싱크 오차가 누적될 수 있습니다. 정밀한 컷이 필요하면 기본 `precise`를 쓰세요.

### 오디오 품질
precise 모드는 필터를 거쳐 오디오를 재인코딩합니다. 손실을 최소화하도록:
- **오디오 전용 파일**(wav → PCM, flac → FLAC)은 **무손실**로 출력합니다.
- 그 외(영상 파일, mp3 등)는 **소스 오디오 비트레이트에 맞춰** AAC로 인코딩합니다(모르면 192k).
- copy 모드는 오디오도 스트림 복사라 **손실이 전혀 없습니다.**

## 진행 표시
처리 중에는 파일별로 실시간 진행바가 stderr에 표시됩니다:
```
처리 중: recording.mp4
  [############------------------]  42.0%
```
`--json`이거나 출력이 터미널이 아닐 때(파이프·리다이렉트)는 진행바가 자동으로 숨겨져 로그·JSON이 깨끗하게 유지됩니다.

## 폴더 일괄 처리
- 폴더를 주면 안의 미디어 파일(mp4, mov, mkv, avi, webm, m4v, mp3, wav, m4a, flac, aac, ogg)을 한꺼번에 처리합니다.
- 이미 만들어진 `*_trimmed.*` 출력 파일은 다시 처리하지 않습니다(재실행 안전).

## 종료 코드
- `0` 전체 성공 / `1` 일부 실패 / `2` 사용법·입력 오류

## 개발
```bash
pip install -e ".[dev]"
pytest
```
