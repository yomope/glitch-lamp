#!/usr/bin/env bash
# Petit snippet manuel pour lancer mpv en plein écran sur la source HLS.
# Usage : sudo ./scripts/run_mpv.sh
# (Ne s’exécute pas automatiquement : à lancer seulement quand nécessaire.)

set -euo pipefail

sudo chvt 1
sudo mpv --video-rotate=270 --fs --panscan=1.0 "http://yomope:18000/stream/stream.m3u8"
