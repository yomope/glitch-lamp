#!/usr/bin/env bash

# Lance mpv en plein écran pour le flux HLS local.
exec /usr/bin/mpv --video-rotate=270 --fs --panscan=1.0 "http://yomope:18000/stream/stream.m3u8"
