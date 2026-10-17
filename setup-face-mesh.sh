#!/usr/bin/env bash
# Installs the face-mesh worker for /face-mesh into .venv-face and downloads
# Google's Face Landmarker model and OpenCV's YuNet face detector. The same
# environment runs the mask composite for /composite-masks. Run from the repo root after pulling.
# MediaPipe and OpenCV need these system libraries on Ubuntu:
#   sudo apt install -y libgl1 libegl1 libgles2 libglib2.0-0
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
# OpenCV's YuNet face detector (finds the small faces MediaPipe's own detector misses).
if [ ! -f models/face_detection_yunet_2023mar.onnx ]; then
  curl -fsSL -o models/face_detection_yunet_2023mar.onnx.download \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
  echo "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  models/face_detection_yunet_2023mar.onnx.download" | sha256sum -c -
  mv models/face_detection_yunet_2023mar.onnx.download models/face_detection_yunet_2023mar.onnx
fi
.venv-face/bin/python face_mesh_worker.py --check models/face_landmarker.task models/face_detection_yunet_2023mar.onnx
