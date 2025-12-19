# Glitch Video Player

A Python-based video player that generates and plays infinite glitched clips from YouTube.

## Features
- **Infinite Playback**: Continuously fetches and plays random clips.
- **Glitch Effects**:
    - **Glitch**: Digital noise and color channel shifting.
    - **Datamosh**: Simulated compression artifacts.
    - **Timeslit**: Slit-scan time displacement.
    - **Tracking**: Face mesh tracking visualization.
- **Customizable**:
    - Search keywords.
    - YouTube Playlist support.
    - Clip duration and variation.
    - Toggleable effects.

## Prerequisites
- **Python 3.8+** (Official installer from [python.org](https://www.python.org/downloads/) recommended. **Do not use MSYS2/MinGW Python** as it causes installation issues).
- **FFmpeg**: Must be installed and added to your system PATH.
    - Windows: [Download FFmpeg](https://ffmpeg.org/download.html) and add `bin` folder to PATH.
    - Linux: `sudo apt install ffmpeg`

## Installation

### Windows
Run `scripts/install.bat`

### Linux / Mac
Run `scripts/install.sh`

## Usage

1.  Start the server:
    - Windows: `scripts/start.bat`
    - Linux: `scripts/start.sh`
2.  Open your browser at:
    - **Local**: `http://localhost:8000/static/index.html`
    - **Network**: `http://[YOUR_IP]:8000/static/index.html` (accessible depuis d'autres appareils sur le même réseau)
3.  **Controls**:
    - **P**: Toggle Settings Panel.
    - **F11**: Toggle Fullscreen (Browser feature).

### Accès réseau

Le serveur écoute sur `0.0.0.0:8000` par défaut, ce qui permet l'accès depuis d'autres appareils sur votre réseau local. Pour trouver votre adresse IP :

- **Linux/Mac**: `hostname -I` ou `ip addr show`
- **Windows**: `ipconfig` (cherchez IPv4 Address)

Les autres appareils sur le même réseau peuvent accéder à l'application via `http://[VOTRE_IP]:8000/static/index.html`

## Configuration
Press **P** to open the settings panel.
- **Keywords**: Comma-separated list of search terms (e.g., "glitch art, vhs, datamosh").
- **Playlist URL**: Optional YouTube playlist URL. If provided, clips will be pulled from here instead of search.
- **Duration**: Base duration of each clip in seconds.
- **Variation**: Random variation in duration (+/- seconds).
- **Active Effects**: Check/uncheck effects to enable/disable them.

## Troubleshooting
- **Download Failed**: Ensure `yt-dlp` is up to date (re-run install script) and FFmpeg is installed.
- **Video Stuttering**: Processing effects is CPU intensive. Reduce resolution or disable heavy effects like Tracking.
