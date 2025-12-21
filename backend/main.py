import os
import sys
import importlib
import pkgutil
import inspect
import json
import hashlib
import threading
import time

# Add backend dir to PATH to find ffmpeg.exe if present (Windows)
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(backend_dir, os.pardir))
frontend_dir = os.path.join(project_root, "frontend")
ffmpeg_exe_path = os.path.join(backend_dir, "ffmpeg.exe")
if os.path.exists(ffmpeg_exe_path):
    print(f"Found ffmpeg.exe in {backend_dir}, adding to PATH")
    os.environ["PATH"] = backend_dir + os.pathsep + os.environ["PATH"]
else:
    # On Linux/Mac, ffmpeg should be in system PATH
    import shutil
    if shutil.which("ffmpeg"):
        print(f"Using system ffmpeg: {shutil.which('ffmpeg')}")
    else:
        print("WARNING: FFmpeg not found in system PATH")

# Import logger
from backend.utils.logger import logger

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import random
import asyncio
import glob
import shutil
import subprocess
import tempfile
import math
from datetime import datetime

from backend.services.youtube_service import YouTubeService
from backend.services.effect_manager import EffectManager
from backend.services.stats_service import StatsService
from backend.services.streaming_service import streaming_service
from backend.plugins.base import VideoEffect

def detect_uvicorn_binding(default_host="0.0.0.0", default_port=8000):
    """Récupère l'hôte et le port utilisés par uvicorn (CLI/env)."""
    host = os.environ.get("UVICORN_HOST") or os.environ.get("HOST") or default_host
    port_env = os.environ.get("UVICORN_PORT") or os.environ.get("PORT")
    try:
        port = int(port_env) if port_env else default_port
    except (TypeError, ValueError):
        port = default_port

    argv = sys.argv[1:]

    def _arg_value(flag: str):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                return argv[idx + 1]
        return None

    host_arg = _arg_value("--host") or _arg_value("-h")
    port_arg = _arg_value("--port") or _arg_value("-p")
    if host_arg:
        host = host_arg
    if port_arg:
        try:
            port = int(port_arg)
        except ValueError:
            pass
    return host, port

def load_all_plugins(manager: EffectManager):
    """Dynamically discover and register every VideoEffect in backend.plugins."""
    try:
        import backend.plugins as plugins_pkg
    except ImportError as e:
        print(f"Failed to import plugins package: {e}")
        return

    for _, modname, ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
        if modname.startswith("_") or modname == "base" or ispkg:
            continue
        try:
            module = importlib.import_module(f"backend.plugins.{modname}")
        except Exception as e:
            print(f"Skipping plugin {modname}: import failed ({e})")
            continue

        registered = False
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, VideoEffect) and obj is not VideoEffect:
                try:
                    manager.register_effect(obj())
                    registered = True
                except Exception as e:
                    print(f"Skipping {modname}.{obj.__name__}: init failed ({e})")

        if not registered:
            print(f"No VideoEffect subclass found in plugin {modname}")

app = FastAPI(title="Glitch Video Player")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Services
yt_service = YouTubeService()
effect_manager = EffectManager()
stats_service = StatsService()

# Register Effects dynamically
load_all_plugins(effect_manager)

# State
class Settings(BaseModel):
    duration: int = 5
    duration_variation: int = 2
    keywords: str = "glitch art, datamosh, vhs aesthetic"
    playlist_url: Optional[str] = None
    local_file: Optional[str] = None  # Nom du fichier uploadé
    active_effects: List[str] = ["glitch"]
    effect_options: Dict[str, Dict[str, Any]] = {}
    effect_chain: List[Dict[str, Any]] = []
    randomize_effects: bool = False
    random_preset_mode: bool = False
    freestyle_mode: bool = False
    min_replays_before_next: int = 1
    playback_speed: float = 1.0
    video_quality: str = "best"  # best, 1080p, 720p, 480p
    include_reels: bool = True

SETTINGS_FILE = os.path.join(backend_dir, "settings.json")
PRESETS_DIR = os.path.join(backend_dir, "presets")
os.makedirs(PRESETS_DIR, exist_ok=True)


def load_settings_from_disk() -> Settings:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Settings(**data)
    except FileNotFoundError:
        return Settings()
    except Exception as e:
        print(f"Failed to load settings file, using defaults: {e}")
        return Settings()


def save_settings_to_disk(settings: Settings) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings.dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save settings file: {e}")


current_settings = load_settings_from_disk()

# Ensure temp directory exists
os.makedirs("temp_videos", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("exports", exist_ok=True)
PLAYLIST_FILE = os.path.join(backend_dir, "playlist.json")
playlist_items: List[Dict[str, Any]] = []
playlist_cursor = 0
playlist_lock = threading.Lock()


def load_playlist() -> List[Dict[str, Any]]:
    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"Failed to load playlist: {e}")
        return []


def save_playlist():
    try:
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(playlist_items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save playlist: {e}")


playlist_items = load_playlist()
HLS_DIR = os.path.join(os.getcwd(), "hls")
os.makedirs(HLS_DIR, exist_ok=True)

hls_segments = []  # liste de tuples (seq, filename, duration)
hls_lock = threading.Lock()
hls_seq = 0
HLS_MAX_SEGMENTS = 60
HLS_PLAYLIST = os.path.join(HLS_DIR, "stream.m3u8")


def rebuild_hls_from_playlist():
    """Reconstruit l'état HLS en mémoire à partir du fichier stream.m3u8."""
    global hls_segments, hls_seq
    if not os.path.exists(HLS_PLAYLIST):
        return
    try:
        with open(HLS_PLAYLIST, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines()]
        media_seq = 0
        for line in lines:
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                try:
                    media_seq = int(line.split(":")[1])
                except Exception:
                    media_seq = 0
                break
        segments = []
        for i, line in enumerate(lines):
            if line.startswith("#EXTINF:") and i + 1 < len(lines):
                try:
                    dur = float(line.replace("#EXTINF:", "").replace(",", ""))
                except ValueError:
                    dur = 0.0
                fname = lines[i + 1]
                if os.path.exists(os.path.join(HLS_DIR, fname)):
                    seq = media_seq + len(segments)
                    segments.append((seq, fname, dur))
        if segments:
            hls_segments = segments
            hls_seq = hls_segments[-1][0] + 1
    except Exception as e:
        logger.error(f"Rebuild HLS playlist failed: {e}")


def rebuild_hls_from_filesystem():
    """Fallback: reconstruit l'état depuis les fichiers .ts présents."""
    global hls_segments, hls_seq
    try:
        ts_files = [f for f in os.listdir(HLS_DIR) if f.endswith(".ts")]
        ts_files.sort()
        segments = []
        for idx, fname in enumerate(ts_files):
            if os.path.exists(os.path.join(HLS_DIR, fname)):
                segments.append((idx, fname, 0.0))
        if segments:
            hls_segments = segments
            hls_seq = hls_segments[-1][0] + 1
    except Exception as e:
        logger.error(f"Rebuild HLS from filesystem failed: {e}")


def reset_hls():
    """Réinitialise complètement le buffer HLS (segments + playlist)."""
    global hls_segments, hls_seq
    with hls_lock:
        hls_segments = []
        hls_seq = 0
        try:
            if os.path.isdir(HLS_DIR):
                for fn in os.listdir(HLS_DIR):
                    try:
                        os.remove(os.path.join(HLS_DIR, fn))
                    except Exception:
                        pass
        except Exception:
            pass


def write_hls_playlist():
    """Réécrit la playlist HLS à partir des segments connus."""
    global hls_segments
    # Nettoyer les entrées dont le fichier n'existe plus
    hls_segments = sorted(
        [(seq, fname, dur) for (seq, fname, dur) in hls_segments if os.path.exists(os.path.join(HLS_DIR, fname))],
        key=lambda x: x[0]
    )
    if not hls_segments:
        return
    target = max(1, math.ceil(max(seg[2] for seg in hls_segments)))
    media_seq = hls_segments[0][0]
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-PLAYLIST-TYPE:EVENT",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        f"#EXT-X-TARGETDURATION:{target}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_seq}",
    ]
    for _, fname, dur in hls_segments:
        lines.append(f"#EXTINF:{dur:.3f},")
        lines.append(fname)
    lines.append("#EXT-X-DISCONTINUITY")
    with open(HLS_PLAYLIST, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_clip_to_hls(video_path: str, segment_time: int = 4):
    """Segmenter un clip en TS et l'ajouter à la playlist live."""
    global hls_seq, hls_segments
    if not os.path.exists(video_path):
        return

    with hls_lock:
        tmp_dir = tempfile.mkdtemp(prefix="hls_seg_")
        start_number = hls_seq
        unique_prefix = f"seg_{int(time.time() * 1000)}_{start_number:010d}"
        segment_pattern = os.path.join(tmp_dir, f"{unique_prefix}_%03d.ts")
        playlist_tmp = os.path.join(tmp_dir, "playlist.m3u8")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-codec",
            "copy",
            "-map",
            "0",
            "-f",
            "segment",
            "-segment_time",
            str(segment_time),
            "-segment_format",
            "mpegts",
            "-start_number",
            "0",
            "-segment_list",
            playlist_tmp,
            "-segment_list_type",
            "m3u8",
            segment_pattern,
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        except Exception as e:
            logger.error(f"Segmentation HLS échouée: {e}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # Lire la playlist générée pour récupérer durées et fichiers
        new_segments = []
        try:
            with open(playlist_tmp, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines()]
            for i, line in enumerate(lines):
                if line.startswith("#EXTINF:") and i + 1 < len(lines):
                    try:
                        dur = float(line.replace("#EXTINF:", "").replace(",", ""))
                    except ValueError:
                        dur = segment_time
                    fname = os.path.basename(lines[i + 1])
                    new_segments.append((start_number + len(new_segments), fname, dur))
        except Exception as e:
            logger.error(f"Lecture playlist HLS temp échouée: {e}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # Déplacer les segments dans le dossier HLS
        for _, fname, _ in new_segments:
            src = os.path.join(tmp_dir, fname)
            dst = os.path.join(HLS_DIR, fname)
            try:
                shutil.move(src, dst)
            except Exception as e:
                logger.warning(f"Impossible de déplacer {fname} vers HLS: {e}")

        shutil.rmtree(tmp_dir, ignore_errors=True)

        # Mettre à jour la liste globale
        hls_segments.extend(new_segments)
        hls_seq = new_segments[-1][0] + 1 if new_segments else hls_seq

        # Garder seulement les segments récents
        if len(hls_segments) > HLS_MAX_SEGMENTS:
            to_remove = hls_segments[:-HLS_MAX_SEGMENTS]
            hls_segments = hls_segments[-HLS_MAX_SEGMENTS:]
            for _, fname, _ in to_remove:
                try:
                    os.remove(os.path.join(HLS_DIR, fname))
                except Exception:
                    pass

        # Nettoyer les entrées dont le fichier a disparu
        hls_segments = [(seq, fname, dur) for (seq, fname, dur) in hls_segments if os.path.exists(os.path.join(HLS_DIR, fname))]

        write_hls_playlist()

def hls_segments_state():
    """Retourne l'état courant des segments HLS."""
    # Reconstruire à chaque requête pour refléter l'état disque et dédupliquer
    if os.path.exists(HLS_PLAYLIST):
        rebuild_hls_from_playlist()
    elif not hls_segments:
        rebuild_hls_from_filesystem()
    write_hls_playlist()
    with hls_lock:
        return [
            {
                "seq": seq,
                "filename": fname,
                "duration": dur,
                "exists": os.path.exists(os.path.join(HLS_DIR, fname))
            } for (seq, fname, dur) in hls_segments
        ]

def delete_hls_segment(seq: int):
    """Supprime un segment HLS par séquence."""
    global hls_segments
    with hls_lock:
        to_delete = [fname for (s, fname, _) in hls_segments if s == seq]
        hls_segments = [(s, fname, dur) for (s, fname, dur) in hls_segments if s != seq]
        for fname in to_delete:
            try:
                os.remove(os.path.join(HLS_DIR, fname))
            except Exception:
                pass
        write_hls_playlist()


def get_next_playlist_entry() -> Optional[Dict[str, Any]]:
    """Retourne la prochaine entrée de playlist (rotation circulaire)."""
    global playlist_cursor
    with playlist_lock:
        if not playlist_items:
            return None
        entry = playlist_items[playlist_cursor % len(playlist_items)]
        playlist_cursor = (playlist_cursor + 1) % len(playlist_items)
        return entry.copy()

# Cache pour éviter les re-téléchargements (video_url + start_time + duration -> processed_path)
video_cache = {}
cache_lock = threading.Lock()

# Gestionnaire de clip actuel pour le streaming
current_streaming_clip: Optional[str] = None
streaming_clip_lock = threading.Lock()
is_generating_next = False

# Nettoyage automatique des fichiers temporaires
def cleanup_temp_files(max_age_hours=24, max_files=50):
    """Nettoie les fichiers temporaires anciens."""
    try:
        files = glob.glob(os.path.join("temp_videos", "*.mp4"))
        current_time = time.time()
        removed_count = 0
        
        # Trier par date de modification
        files_with_time = [(f, os.path.getmtime(f)) for f in files]
        files_with_time.sort(key=lambda x: x[1])
        
        for filepath, mtime in files_with_time:
            age_hours = (current_time - mtime) / 3600
            
            # Supprimer si trop vieux ou si trop de fichiers
            if age_hours > max_age_hours or len(files_with_time) - removed_count > max_files:
                try:
                    os.remove(filepath)
                    removed_count += 1
                    logger.debug(f"Removed old temp file: {os.path.basename(filepath)}")
                except Exception as e:
                    logger.warning(f"Failed to remove {filepath}: {e}")
        
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old temporary files")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# Nettoyage périodique (toutes les heures)
def start_cleanup_thread():
    """Démarre un thread pour le nettoyage périodique."""
    def cleanup_loop():
        while True:
            time.sleep(3600)  # Attendre 1 heure
            cleanup_temp_files()
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    logger.info("Started automatic cleanup thread")

# Mount static files
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
app.mount("/videos", StaticFiles(directory="temp_videos"), name="videos")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/exports", StaticFiles(directory="exports"), name="exports")
app.mount("/stream", StaticFiles(directory=HLS_DIR), name="stream")

@app.on_event("startup")
async def startup_event():
    import socket
    uvicorn_host, uvicorn_port = detect_uvicorn_binding()
    reset_hls()
    # Obtenir l'IP locale
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    
    logger.info("="*60)
    logger.info("🚀 Glitch Video Player is ready!")
    logger.info(f"Serveur uvicorn: http://{uvicorn_host}:{uvicorn_port}")
    logger.info(f"Frontend available at:")
    logger.info(f"  - Local: http://127.0.0.1:{uvicorn_port}/static/index.html")
    logger.info(f"  - Network: http://{local_ip}:{uvicorn_port}/static/index.html")
    logger.info(f"Flux HLS: http://{local_ip}:{uvicorn_port}/stream/stream.m3u8")
    logger.info("="*60)
    # Nettoyage initial et démarrage du thread
    cleanup_temp_files()
    start_cleanup_thread()
    
    # Générer le premier clip pour le streaming
    asyncio.create_task(generate_next_clip_async())
    
    # Démarrer la boucle de génération automatique
    asyncio.create_task(streaming_loop())

@app.get("/")
async def root():
    return {"message": "Glitch Video Player API is running"}

@app.get("/settings", response_model=Settings)
async def get_settings():
    return current_settings

@app.post("/settings")
async def update_settings(settings: Settings):
    global current_settings
    current_settings = settings
    save_settings_to_disk(current_settings)
    # effect_manager.set_active_effects(settings.active_effects) # Removed
    return current_settings

@app.get("/effects")
async def get_effects():
    return effect_manager.get_available_effects()

@app.get("/presets")
async def list_presets():
    """List all saved presets."""
    presets = []
    for filename in os.listdir(PRESETS_DIR):
        if filename.endswith(".json"):
            presets.append(filename[:-5])
    return presets

@app.get("/presets/{name}")
async def get_preset(name: str):
    """Load a specific preset."""
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Preset not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/presets/{name}")
async def save_preset(name: str, chain: List[Dict[str, Any]]):
    """Save a preset."""
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chain, f, ensure_ascii=False, indent=2)
        return {"message": "Preset saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/presets/{name}")
async def delete_preset(name: str):
    """Delete a preset."""
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"message": "Preset deleted"}
    raise HTTPException(status_code=404, detail="Preset not found")

@app.get("/videos/random")
async def get_random_video():
    """Returns a random existing processed video if available."""
    files = glob.glob(os.path.join("temp_videos", "processed_*.mp4"))
    if files:
        selected = random.choice(files)
        return {"url": f"/videos/{os.path.basename(selected)}"}
    return {"url": None}

def _is_reel(entry: Dict[str, Any]) -> bool:
    url = entry.get('url') or entry.get('webpage_url') or ""
    duration = entry.get('duration')
    if url and "shorts/" in url:
        return True
    if duration is not None and duration <= 90:
        return True
    return False


def generate_clip_sync(settings: Settings, max_retries=3):
    """Synchronous function to handle the entire clip generation process with retry logic."""
    logger.info(f"Generating clip with settings: duration={settings.duration}, effects={len(settings.effect_chain)}")
    
    for attempt in range(max_retries):
        try:
            # 1. Select Video Source
            video_url = None
            video = None
            raw_path = None
            playlist_entry = None
            
            # Priorité 1: Fichier local uploadé
            if settings.local_file:
                local_file_path = os.path.join("uploads", settings.local_file)
                if os.path.exists(local_file_path):
                    logger.info(f"Using local file: {settings.local_file}")
                    raw_path = local_file_path
                    # Pour les fichiers locaux, on utilise la durée complète ou celle spécifiée
                    video_duration = settings.duration
                else:
                    logger.warning(f"Local file not found: {settings.local_file}")

            # Priorité 2: Playlist interne
            if not raw_path and not video_url:
                playlist_entry = get_next_playlist_entry()
                if playlist_entry:
                    if playlist_entry.get("local_file"):
                        candidate = os.path.join("uploads", playlist_entry["local_file"])
                        if os.path.exists(candidate):
                            raw_path = candidate
                            logger.info(f"Using playlist local file: {playlist_entry['local_file']}")
                        else:
                            logger.warning(f"Playlist file not found: {playlist_entry['local_file']}")
                    elif playlist_entry.get("url"):
                        video_url = playlist_entry["url"]
                        logger.info(f"Using playlist url: {video_url}")
            
            # Priorité 2: Playlist YouTube
            if not raw_path and settings.playlist_url:
                logger.debug(f"Checking playlist: {settings.playlist_url}")
                videos = yt_service.get_playlist_videos(settings.playlist_url)
                if videos:
                    valid_videos = [v for v in videos if v.get('duration') and v.get('duration') <= 1200]
                    if not settings.include_reels:
                        valid_videos = [v for v in valid_videos if not _is_reel(v)]
                    logger.debug(f"Found {len(valid_videos)} valid videos in playlist")
                    if valid_videos:
                        video = random.choice(valid_videos)
                        video_url = video['url']
            
            if not video_url:
                # Fallback to search
                keywords = [k.strip() for k in settings.keywords.split(",")]
                if not keywords: keywords = ["glitch art"]
                keyword = random.choice(keywords)
                logger.debug(f"Searching for keyword: {keyword}")
                videos = yt_service.search_videos(keyword)
                if videos:
                    valid_videos = [v for v in videos if v.get('duration') and v.get('duration') <= 1200]
                    if not settings.include_reels:
                        valid_videos = [v for v in valid_videos if not _is_reel(v)]
                    logger.debug(f"Found {len(valid_videos)} valid videos from search")
                    if valid_videos:
                        video = random.choice(valid_videos)
                        video_url = video['url']
                    else:
                        logger.warning("No videos <= 20 mins found in search results")
                else:
                    logger.warning("No videos found from search")
                    
            if not video_url:
                raise Exception("No videos found")

            logger.info(f"Selected video: {video_url}")

            # 2. Determine Duration
            duration = settings.duration + random.randint(-settings.duration_variation, settings.duration_variation)
            if duration < 1: duration = 1
            
            # 3. Check cache
            cache_key = hashlib.md5(f"{video_url}_{duration}_{settings.video_quality}_{json.dumps(settings.effect_chain, sort_keys=True)}".encode()).hexdigest()
            
            with cache_lock:
                if cache_key in video_cache:
                    cached_path = video_cache[cache_key]
                    if os.path.exists(os.path.join("temp_videos", os.path.basename(cached_path))):
                        logger.info(f"Using cached clip: {cached_path}")
                        return cached_path
            
            # 4. Download Clip (si pas déjà un fichier local)
            if not raw_path:
                video_duration = video.get('duration', 600)
                if not video_duration: video_duration = 600
                
                start_time = random.randint(0, max(0, int(video_duration) - duration))
                logger.info(f"Downloading clip: start={start_time}, duration={duration}")
                
                raw_path = yt_service.download_clip(video_url, start_time, duration, settings.video_quality)
                
                if not raw_path:
                    logger.warning(f"Download failed for video {video_url}, attempt {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        time.sleep(2)  # Attendre avant retry
                        continue
                    raise Exception(f"Download failed for video {video_url} after {max_retries} attempts")
                
                logger.info(f"Download complete: {raw_path}")
            else:
                # Pour les fichiers locaux, extraire un segment si nécessaire
                if settings.duration > 0:
                    # Copier le fichier et extraire un segment avec FFmpeg
                    import subprocess
                    import shutil
                    backend_dir = os.path.dirname(os.path.abspath(__file__))
                    ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
                    import sys
                    is_windows = os.name == 'nt' or sys.platform.startswith('win')
                    
                    if is_windows and os.path.exists(ffmpeg_local_exe):
                        ffmpeg_exe = ffmpeg_local_exe
                    else:
                        import shutil as shutil_module
                        ffmpeg_exe = shutil_module.which("ffmpeg") or "ffmpeg"
                    
                    # Obtenir la durée du fichier
                    try:
                        result = subprocess.run([
                            ffmpeg_exe, '-i', raw_path, '-hide_banner'
                        ], capture_output=True, stderr=subprocess.PIPE, text=True)
                        # Parser la durée depuis la sortie (simplifié)
                        duration_seconds = settings.duration
                        start_time = 0  # Commencer au début pour les fichiers locaux
                    except:
                        duration_seconds = settings.duration
                        start_time = 0
                    
                    # Extraire le segment si nécessaire
                    if duration_seconds < 600:  # Si on veut moins de 10 minutes
                        temp_segment = raw_path.replace(".mp4", f"_segment_{int(time.time())}.mp4")
                        try:
                            subprocess.run([
                                ffmpeg_exe, '-y', '-i', raw_path,
                                '-ss', str(start_time),
                                '-t', str(duration_seconds),
                                '-c', 'copy', temp_segment
                            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                            raw_path = temp_segment
                        except:
                            pass  # Utiliser le fichier complet si l'extraction échoue
                
            # 5. Apply Effects
            output_filename = f"processed_{os.path.basename(raw_path)}"
            output_path = os.path.join("temp_videos", output_filename)
            
            # Build effect chain
            effect_chain = []

            if settings.freestyle_mode:
                logger.debug("Freestyle mode active: Generating random effect chain")
                effect_chain = effect_manager.generate_random_chain()
            elif settings.random_preset_mode:
                logger.debug("Random Preset mode active: Picking random preset")
                presets = [f[:-5] for f in os.listdir(PRESETS_DIR) if f.endswith(".json")]
                if presets:
                    preset_name = random.choice(presets)
                    logger.debug(f"Selected random preset: {preset_name}")
                    try:
                        with open(os.path.join(PRESETS_DIR, f"{preset_name}.json"), "r", encoding="utf-8") as f:
                            effect_chain = json.load(f)
                    except Exception as e:
                        logger.error(f"Failed to load random preset {preset_name}: {e}")
                else:
                    logger.warning("No presets found for Random Preset mode")

            if not effect_chain:
                effect_chain = settings.effect_chain[:] if settings.effect_chain else []
                if not effect_chain:
                    for name in settings.active_effects:
                        effect_chain.append({"name": name, "options": settings.effect_options.get(name, {})})

            # Fill defaults and optionally randomize
            for entry in effect_chain:
                name = entry.get("name")
                defaults = effect_manager.get_default_options_for_effect(name)
                opts = entry.get("options", {}) or {}
                for k, v in defaults.items():
                    opts.setdefault(k, v)
                entry["options"] = opts

            if settings.randomize_effects:
                logger.debug("Randomizing effect options per chain element...")
                for entry in effect_chain:
                    name = entry.get("name")
                    random_opts = effect_manager.get_random_options_for_effect(name)
                    entry_opts = entry.get("options", {}) or {}
                    entry_opts.update(random_opts)
                    entry["options"] = entry_opts

            logger.info(f"Applying effects chain: {[e.get('name') for e in effect_chain]}")
            processed_path = effect_manager.process_video(
                raw_path,
                output_path,
                effect_chain=effect_chain,
                effect_options=settings.effect_options,
                active_effects_names=settings.active_effects,
            )
            
            if not processed_path or not os.path.exists(processed_path):
                logger.error(f"Processing failed, output file not found")
                if attempt < max_retries - 1:
                    continue
                raise Exception("Video processing failed")
            
            logger.info(f"Processing complete: {processed_path}")
            
            result_url = f"/videos/{os.path.basename(processed_path)}"
            
            # Ajouter à l'historique (fait automatiquement par le streaming service)
            
            # Mettre en cache
            with cache_lock:
                video_cache[cache_key] = result_url
                # Limiter la taille du cache
                if len(video_cache) > 100:
                    # Supprimer les entrées les plus anciennes
                    oldest_key = next(iter(video_cache))
                    del video_cache[oldest_key]
            
            return result_url
            
        except Exception as e:
            logger.error(f"Error generating clip (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    
    raise Exception(f"Failed to generate clip after {max_retries} attempts")

@app.get("/clip")
async def get_clip():
    """Endpoint pour obtenir le clip actuel (pour compatibilité)"""
    state = streaming_service.get_state()
    if state["current_video"]:
        return {"url": state["current_video"]}
    # Générer un nouveau clip si aucun n'est disponible
    result = await generate_next_clip_async(force=True)
    if result:
        return {"url": result["url"]}
    return {"url": None}

async def generate_next_clip_async(force: bool = False):
    """Génère le prochain clip pour le streaming (fonction async).

    - force=True : génération explicite (même sans clients).
    - force=False : génération seulement si nécessaire (clients connectés, pas de next prêt).
    """
    global is_generating_next
    
    if is_generating_next:
        return
    
    is_generating_next = True
    loop = asyncio.get_event_loop()
    
    try:
        state_snapshot = streaming_service.get_state()
        client_count = streaming_service.client_count()

        if not force:
            if state_snapshot.get("next_video"):
                logger.debug("Skip génération: next déjà prêt, rien à faire.")
                return {"status": "skipped", "reason": "next_ready"}
            if client_count == 0:
                logger.debug("Skip génération: aucun client connecté.")
                return {"status": "skipped", "reason": "no_clients"}

        logger.info("Génération du prochain clip pour le streaming...")
        # Générer le clip en arrière-plan
        url = await loop.run_in_executor(None, generate_clip_sync, current_settings)
        repeats_target = max(0, getattr(current_settings, "min_replays_before_next", 0))
        
        # Obtenir la durée du clip
        video_path = url.replace("/videos/", "temp_videos/")
        duration = 0.0
        if os.path.exists(video_path):
            try:
                import cv2
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    if fps > 0:
                        duration = frame_count / fps
                    cap.release()
            except:
                duration = current_settings.duration
        
        # Si c'est la première vidéo, la définir comme actuelle
        state = streaming_service.get_state()
        if not state["current_video"]:
            streaming_service.set_current_video(url, duration, repeats_target=repeats_target, path=video_path)
            await streaming_service.switch_video(url, duration, repeats_target=repeats_target, path=video_path)
            logger.info(f"Première vidéo diffusée: {url}")
        else:
            # Sinon, la préparer comme prochaine vidéo
            streaming_service.set_next_video(url)
            logger.info(f"Prochaine vidéo préparée: {url}")

        # Ajouter au flux HLS continu
        try:
            append_clip_to_hls(video_path)
        except Exception as e:
            logger.error(f"Erreur lors de l'ajout au flux HLS: {e}")
        
        return {"url": url, "duration": duration, "status": "ready"}
    except Exception as e:
        logger.error(f"Error generating clip: {e}")
        # Réessayer après un délai
        await asyncio.sleep(5)
        asyncio.create_task(generate_next_clip_async(force=force))
    finally:
        is_generating_next = False

@app.post("/streaming/generate-next")
async def generate_next_clip_endpoint():
    """Endpoint pour générer manuellement le prochain clip."""
    asyncio.create_task(generate_next_clip_async(force=True))
    return {"status": "generating"}

async def streaming_loop():
    """Boucle principale de gestion du streaming."""
    while True:
        try:
            await asyncio.sleep(1)  # Vérifier toutes les secondes
            client_count = streaming_service.client_count()

            # Sans clients, on fige la lecture et on évite de générer inutilement
            if client_count == 0:
                if streaming_service.is_playing:
                    try:
                        await streaming_service.pause()
                    except Exception as e:
                        logger.error(f"Pause auto (pas de clients) échouée: {e}")
                continue
            else:
                if not streaming_service.is_playing:
                    try:
                        await streaming_service.play()
                    except Exception as e:
                        logger.error(f"Lecture auto (clients présents) échouée: {e}")

            repeats_target = max(0, getattr(current_settings, "min_replays_before_next", 0))
            
            state = streaming_service.get_state()
            if not state["current_video"]:
                # Pas de vidéo actuelle, générer une nouvelle
                await generate_next_clip_async()
                continue
            
            # Vérifier si la vidéo actuelle est terminée
            current_pos = streaming_service.get_current_position()
            duration = state["duration"]
            
            # Si on approche de la fin (à 2 secondes près), préparer la transition
            if duration > 0 and current_pos >= duration - 2.0:
                # Si on a déjà une prochaine vidéo préparée, faire la transition
                if state["next_video"]:
                    # Enregistrer le clip terminé (en tenant compte des répétitions réalisées)
                    repeats_done = max(1, streaming_service.repeat_count + 1)
                    try:
                        stats_service.record_clip_played(duration * repeats_done)
                    except Exception as e:
                        logger.error(f"Stats record failed: {e}")
                    try:
                        await add_to_history_async({
                            "url": state["current_video"],
                            "duration": duration * repeats_done
                        })
                    except Exception as e:
                        logger.error(f"History record failed: {e}")
                    
                    # Obtenir la durée de la prochaine vidéo
                    next_video_path = state["next_video"].replace("/videos/", "temp_videos/")
                    next_duration = duration
                    if os.path.exists(next_video_path):
                        try:
                            import cv2
                            cap = cv2.VideoCapture(next_video_path)
                            if cap.isOpened():
                                fps = cap.get(cv2.CAP_PROP_FPS)
                                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                                if fps > 0:
                                    next_duration = frame_count / fps
                                cap.release()
                        except:
                            pass
                    
                    await streaming_service.switch_video(state["next_video"], next_duration, repeats_target=repeats_target, path=next_video_path)
                    # Générer la prochaine vidéo en arrière-plan
                    asyncio.create_task(generate_next_clip_async())
                else:
                    # Pas de prochaine vidéo prête : boucler en réinjectant le clip courant dans le HLS
                    current_path = streaming_service.current_video_path
                    if current_path and os.path.exists(current_path):
                        append_clip_to_hls(current_path)
                        streaming_service.note_repeat()
                        logger.info("Boucle serveur: réinjection du clip courant dans le flux HLS en attendant la prochaine vidéo")
                    if not is_generating_next:
                        asyncio.create_task(generate_next_clip_async())
            
        except Exception as e:
            logger.error(f"Error in streaming loop: {e}")
            await asyncio.sleep(5)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket pour la synchronisation."""
    await websocket.accept()
    await streaming_service.add_client(websocket)
    
    try:
        # Envoyer l'état actuel au nouveau client
        state = streaming_service.get_state()
        await websocket.send_json({
            "type": "state",
            **state
        })
        
        # Écouter les messages du client
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "play":
                await streaming_service.play()
            elif msg_type == "pause":
                await streaming_service.pause()
            elif msg_type == "seek":
                position = data.get("position", 0)
                await streaming_service.seek(position)
            elif msg_type == "speed":
                speed = data.get("speed", 1.0)
                await streaming_service.set_speed(speed)
            elif msg_type == "get_state":
                state = streaming_service.get_state()
                await websocket.send_json({
                    "type": "state",
                    **state
                })
                
    except WebSocketDisconnect:
        await streaming_service.remove_client(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await streaming_service.remove_client(websocket)

@app.get("/stats")
async def get_stats():
    """Retourne les statistiques de lecture."""
    stats = stats_service.get_stats()
    # Formater le temps pour l'affichage
    stats["total_playback_time_formatted"] = stats_service.format_time(stats["total_playback_time"])
    stats["playback_time_today_formatted"] = stats_service.format_time(stats["playback_time_today"])
    stats["session_duration_formatted"] = stats_service.format_time(stats.get("session_duration", 0))
    return stats

@app.post("/stats/record")
async def record_clip_played(request: Dict[str, Any]):
    """Enregistre qu'un clip a été joué."""
    duration = request.get("duration", 0.0)
    if isinstance(duration, (int, float)) and duration > 0:
        stats_service.record_clip_played(float(duration))
    return {"status": "recorded"}

@app.post("/stats/reset")
async def reset_stats():
    """Réinitialise les statistiques."""
    stats_service.reset_stats()
    return {"status": "reset"}

# ===== UPLOAD ET EXPORT =====

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload un fichier vidéo local."""
    try:
        # Vérifier l'extension
        if not file.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
            raise HTTPException(status_code=400, detail="Format de fichier non supporté")
        
        # Sauvegarder le fichier
        timestamp = int(time.time() * 1000)
        filename = f"upload_{timestamp}_{file.filename}"
        filepath = os.path.join("uploads", filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"File uploaded: {filename}")
        return {"filename": filename, "path": f"/uploads/{filename}"}
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/uploads-list")
async def list_uploaded_files():
    """Liste les fichiers présents dans le dossier uploads."""
    try:
        files = []
        for filename in os.listdir("uploads"):
            path = os.path.join("uploads", filename)
            if os.path.isfile(path):
                stat = os.stat(path)
                files.append({
                    "filename": filename,
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        files.sort(key=lambda x: x["created"], reverse=True)
        return files
    except Exception as e:
        logger.error(f"Error listing uploads: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/playlist")
async def get_playlist():
    """Retourne la playlist courante."""
    with playlist_lock:
        return playlist_items

@app.get("/ui/playlist")
async def playlist_ui():
    """Page de gestion des sources de playlist."""
    return FileResponse(os.path.join(frontend_dir, "playlist.html"))

@app.get("/ui/hls")
async def hls_ui():
    """Page de gestion des segments HLS."""
    return FileResponse(os.path.join(frontend_dir, "hls.html"))

@app.get("/api/stream/segments")
async def get_hls_segments():
    """Retourne la liste des segments HLS connus."""
    return hls_segments_state()

@app.post("/api/stream/reset")
async def reset_hls_endpoint():
    """Réinitialise complètement la playlist HLS (segments + playlist)."""
    reset_hls()
    return {"status": "reset"}

@app.delete("/api/stream/segment/{seq}")
async def delete_hls_segment_endpoint(seq: int):
    delete_hls_segment(seq)
    return {"status": "deleted", "seq": seq}

@app.post("/playlist")
async def add_playlist_item(item: Dict[str, Any]):
    """Ajoute un élément à la playlist (url ou local_file requis)."""
    url = item.get("url")
    local_file = item.get("local_file")
    title = item.get("title") or ""
    if not url and not local_file:
        raise HTTPException(status_code=400, detail="url ou local_file requis")
    with playlist_lock:
        next_id = (max([it.get("id", 0) for it in playlist_items], default=0) + 1)
        entry = {"id": next_id, "url": url, "local_file": local_file, "title": title}
        playlist_items.append(entry)
        save_playlist()
        return entry

@app.delete("/playlist/{item_id}")
async def delete_playlist_item(item_id: int):
    """Supprime un élément de playlist par id."""
    with playlist_lock:
        before = len(playlist_items)
        playlist_items[:] = [it for it in playlist_items if it.get("id") != item_id]
        if len(playlist_items) == before:
            raise HTTPException(status_code=404, detail="Item not found")
        save_playlist()
        return {"status": "deleted"}

@app.post("/playlist/clear")
async def clear_playlist():
    """Vide la playlist."""
    with playlist_lock:
        playlist_items.clear()
        save_playlist()
        return {"status": "cleared"}

@app.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """Sert un fichier uploadé."""
    filepath = os.path.join("uploads", filename)
    if os.path.exists(filepath):
        return FileResponse(filepath)
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/export")
async def export_clip(request: Dict[str, Any]):
    """Exporte un clip traité."""
    try:
        video_url = request.get("url")
        if not video_url:
            raise HTTPException(status_code=400, detail="URL requise")
        
        # Extraire le nom du fichier depuis l'URL
        filename = video_url.replace("/videos/", "")
        source_path = os.path.join("temp_videos", filename)
        
        if not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="Clip not found")
        
        # Copier vers le dossier exports avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"export_{timestamp}_{filename}"
        export_path = os.path.join("exports", export_filename)
        
        shutil.copy2(source_path, export_path)
        
        logger.info(f"Clip exported: {export_filename}")
        return {
            "filename": export_filename,
            "path": f"/exports/{export_filename}",
            "download_url": f"/exports/{export_filename}"
        }
    except Exception as e:
        logger.error(f"Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/exports/{filename}")
async def get_exported_file(filename: str):
    """Sert un fichier exporté."""
    filepath = os.path.join("exports", filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/exports")
async def list_exports():
    """Liste tous les fichiers exportés."""
    try:
        exports = []
        if os.path.exists("exports"):
            for filename in os.listdir("exports"):
                if filename.endswith(".mp4"):
                    filepath = os.path.join("exports", filename)
                    stat = os.stat(filepath)
                    exports.append({
                        "filename": filename,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "url": f"/exports/{filename}"
                    })
        # Trier par date (plus récent en premier)
        exports.sort(key=lambda x: x["created"], reverse=True)
        return exports
    except Exception as e:
        logger.error(f"Error listing exports: {e}")
        return []

# ===== HISTORIQUE =====

# Historique des clips joués
clip_history = []
history_lock = threading.Lock()
MAX_HISTORY = 100

@app.get("/history")
async def get_history():
    """Retourne l'historique des clips joués."""
    with history_lock:
        return clip_history[-MAX_HISTORY:]  # Derniers 100 clips

async def add_to_history_async(clip_data: Dict[str, Any]):
    """Fonction async pour ajouter à l'historique."""
    with history_lock:
        clip_info = {
            "url": clip_data.get("url"),
            "timestamp": datetime.now().isoformat(),
            "duration": clip_data.get("duration", 0)
        }
        clip_history.append(clip_info)
        # Limiter la taille
        if len(clip_history) > MAX_HISTORY:
            clip_history.pop(0)

@app.post("/history/add")
async def add_to_history(request: Dict[str, Any]):
    """Ajoute un clip à l'historique."""
    await add_to_history_async(request)
    return {"status": "added"}

# ===== IMPORT/EXPORT PRESETS =====

@app.get("/presets/export/{name}")
async def export_preset(name: str):
    """Exporte un preset en JSON téléchargeable."""
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Preset not found")
    return FileResponse(path, media_type="application/json", filename=f"{name}.json")

@app.post("/presets/import")
async def import_preset(file: UploadFile = File(...)):
    """Importe un preset depuis un fichier JSON."""
    try:
        if not file.filename.endswith(".json"):
            raise HTTPException(status_code=400, detail="Le fichier doit être un JSON")
        
        # Lire le contenu
        content = await file.read()
        preset_data = json.loads(content)
        
        # Extraire le nom du preset (depuis le nom du fichier ou demander)
        preset_name = file.filename.replace(".json", "")
        
        # Sauvegarder
        path = os.path.join(PRESETS_DIR, f"{preset_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Preset imported: {preset_name}")
        return {"status": "imported", "name": preset_name}
    except Exception as e:
        logger.error(f"Import preset error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    host, port = detect_uvicorn_binding()
    uvicorn.run(app, host=host, port=port)
