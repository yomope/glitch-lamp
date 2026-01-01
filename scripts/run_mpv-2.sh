#!/usr/bin/env bash

# Lance mpv en plein écran pour le flux HLS local.
# --loop-playlist=inf permet la répétition en boucle sans redémarrer depuis le début
exec /usr/bin/mpv --video-rotate=270 --fs --panscan=1.0 --loop-playlist=inf "http://yomope:18000/stream/stream.m3u8"
