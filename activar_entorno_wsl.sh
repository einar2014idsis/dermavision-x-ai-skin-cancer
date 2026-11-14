#!/usr/bin/env bash
# Activar entorno DermaVision con bibliotecas CUDA de los paquetes pip.
set -euo pipefail
source /opt/dermavision/venv/bin/activate
NVIDIA_LIB_DIRS="$(find /opt/dermavision/venv/lib/python3.12/site-packages/nvidia -type d -name lib -print | paste -sd: -)"
export LD_LIBRARY_PATH="${NVIDIA_LIB_DIRS}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
python -c "import tensorflow as tf; print('TensorFlow', tf.__version__, '| GPU(s):', len(tf.config.list_physical_devices('GPU')))"
