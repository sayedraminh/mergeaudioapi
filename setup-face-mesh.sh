#!/usr/bin/env bash
# Installs the face-mesh worker for /face-mesh into .venv-face and downloads
# Google's Face Landmarker model. Run from the repo root after pulling.
# MediaPipe needs a few system libraries on Ubuntu:
#   sudo apt install -y libgl1 libglib2.0-0 libportaudio2
set -euo pipefail
cd "$(dirname "$0")"
FACE_PYTHON="${FACE_PYTHON:-python3}"
"$FACE_PYTHON" -m venv .venv-face
.venv-face/bin/python -m pip install --upgrade pip >/dev/null
.venv-face/bin/python -m pip install mediapipe==1.1.0
mkdir -p models
if [ ! -f models/face_landmarker.task ]; then
  curl -fsSL -o models/face_landmarker.task.download \
    https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
  mv models/face_landmarker.task.download models/face_landmarker.task
fi
.venv-face/bin/python -c "import cv2, mediapipe; print('face mesh ready: mediapipe', mediapipe.__version__)"
