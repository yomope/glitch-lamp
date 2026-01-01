import os
import sys
import importlib
import pkgutil
import inspect
import json
import hashlib
import threading
import time
import uuid
import logging
from collections import deque

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
from fastapi.responses import FileResponse, StreamingResponse, Response
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
progress_state = {"stage": "idle", "percent": 0, "message": "", "updated_at": time.time()}
progress_lock = threading.Lock()
preview_progress_state = {"stage": "idle", "percent": 0, "message": "", "updated_at": time.time()}
preview_progress_lock = threading.Lock()
log_lock = threading.Lock()
log_buffer = deque(maxlen=400)
workers_lock = threading.Lock()
active_workers = {}  # Dict[str, Dict] - worker_id -> {type, clip_name, preset, status, started_at}
generation_paused = False  # Contrôle de pause de la génération automatique
generation_pause_lock = threading.Lock()

class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with log_lock:
            log_buffer.append(msg)

# Attach memory handler once
if not any(isinstance(h, MemoryLogHandler) for h in logger.handlers):
    mem_handler = MemoryLogHandler()
    mem_handler.setLevel(logging.INFO)
    mem_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(mem_handler)

def register_worker(worker_id: str, worker_type: str, clip_name: str = "", preset: str = ""):
    """Enregistre un worker actif."""
    with workers_lock:
        active_workers[worker_id] = {
            "type": worker_type,
            "clip_name": clip_name,
            "preset": preset if preset else "chaine editeur",
            "status": "running",
            "started_at": time.time()
        }

def update_worker(worker_id: str, clip_name: str = None, preset: str = None, status: str = None):
    """Met à jour les informations d'un worker."""
    with workers_lock:
        if worker_id in active_workers:
            if clip_name is not None:
                active_workers[worker_id]["clip_name"] = clip_name
            if preset is not None:
                active_workers[worker_id]["preset"] = preset if preset else "chaine editeur"
            if status is not None:
                active_workers[worker_id]["status"] = status

def unregister_worker(worker_id: str):
    """Retire un worker."""
    with workers_lock:
        active_workers.pop(worker_id, None)

def get_active_workers() -> Dict[str, Dict]:
    """Retourne la liste des workers actifs."""
    with workers_lock:
        return dict(active_workers)

def set_progress(stage: str, percent: float, message: str = "", preset: str = "", filename: str = "", node: str = "", steps: Optional[List[Dict[str, Any]]] = None):
    with progress_lock:
        progress_state["stage"] = stage
        progress_state["percent"] = max(0.0, min(100.0, percent))
        progress_state["message"] = message
        if preset:
            progress_state["current_preset"] = preset
        if filename:
            progress_state["current_file"] = filename
        if node:
            progress_state["current_node"] = node
        if steps is not None:
            progress_state["steps"] = steps
        progress_state["updated_at"] = time.time()

def set_preview_progress(stage: str, percent: float, message: str = "", preset: str = "", filename: str = "", node: str = "", steps: Optional[List[Dict[str, Any]]] = None):
    with preview_progress_lock:
        preview_progress_state["stage"] = stage
        preview_progress_state["percent"] = max(0.0, min(100.0, percent))
        preview_progress_state["message"] = message
        if preset:
            preview_progress_state["current_preset"] = preset
        if filename:
            preview_progress_state["current_file"] = filename
        if node:
            preview_progress_state["current_node"] = node
        if steps is not None:
            preview_progress_state["steps"] = steps
        preview_progress_state["updated_at"] = time.time()

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
    batch_mode: bool = True  # Mode batch toujours actif
    batch_size: int = 3
    batch_interval: int = 5
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
last_random_preset_name: Optional[str] = None

# Ensure temp directory exists
os.makedirs("temp_videos", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("exports", exist_ok=True)
preview_videos_dir = os.path.join(project_root, "preview_videos")
os.makedirs(preview_videos_dir, exist_ok=True)
PLAYLIST_FILE = os.path.join(backend_dir, "playlist.json")
playlist_items: List[Dict[str, Any]] = []
playlist_cursor = 0
playlist_lock = threading.Lock()
hls_access_lock = threading.Lock()
last_hls_access_ts = 0.0


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
hls_discontinuities = set()  # séquences où un nouveau clip commence
hls_lock = threading.RLock()
hls_seq = 0
HLS_MAX_SEGMENTS = 60
HLS_PLAYLIST = os.path.join(HLS_DIR, "stream.m3u8")
# Suivi des fichiers vidéo déjà ajoutés à la playlist HLS pour éviter les doublons
# Structure: set de (chemin_absolu, taille_fichier) pour identifier de manière unique
hls_added_videos = set()

# Suivi des vidéos déjà utilisées par requête de recherche pour éviter les doublons
# Structure: {query: [video_ids_utilisés]}
youtube_search_used_videos = {}
# Suivi des vidéos qui ont échoué pour éviter de les réessayer immédiatement
# Structure: {query: [video_ids_échoués]}
youtube_search_failed_videos = {}
youtube_search_lock = threading.RLock()


def rebuild_hls_from_playlist():
    """Reconstruit l'état HLS en mémoire à partir du fichier stream.m3u8."""
    global hls_segments, hls_seq, hls_discontinuities
    if not os.path.exists(HLS_PLAYLIST):
        return
    try:
        with hls_lock:
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
            disc_set = set()
            pending_discontinuity = False

            def _seq_from_fname(fname: str, fallback_seq: int) -> int:
                """Déduit le numéro de séquence à partir du nom de fichier."""
                # Format attendu: seg_<timestamp>_<start_seq padded>_<idx>.ts
                try:
                    base, idx = fname.rsplit("_", 1)
                    base_seq = int(base.split("_")[-1])
                    idx_seq = int(idx.replace(".ts", ""))
                    return base_seq + idx_seq
                except Exception:
                    return fallback_seq

            seen_seqs = set()  # Éviter les séquences dupliquées
            for i, line in enumerate(lines):
                if line == "#EXT-X-DISCONTINUITY":
                    pending_discontinuity = True
                    continue
                if line.startswith("#EXTINF:") and i + 1 < len(lines):
                    try:
                        dur = float(line.replace("#EXTINF:", "").replace(",", ""))
                    except ValueError:
                        dur = 0.0
                    fname = lines[i + 1]
                    if os.path.exists(os.path.join(HLS_DIR, fname)):
                        seq = _seq_from_fname(fname, media_seq + len(segments))
                        # Éviter les segments dupliqués
                        if seq not in seen_seqs:
                            seen_seqs.add(seq)
                            if pending_discontinuity:
                                disc_set.add(seq)
                                pending_discontinuity = False
                            segments.append((seq, fname, dur))
                        else:
                            logger.warning(f"Duplicate segment sequence {seq} for {fname}, skipping")
            if segments:
                # Trier par séquence pour garantir l'ordre
                segments.sort(key=lambda x: x[0])
                hls_segments = segments
                valid_seqs = {seq for (seq, _, _) in segments}
                hls_discontinuities = disc_set & valid_seqs
                hls_seq = hls_segments[-1][0] + 1
    except Exception as e:
        logger.error(f"Rebuild HLS playlist failed: {e}")


def rebuild_hls_from_filesystem():
    """Fallback: reconstruit l'état depuis les fichiers .ts présents."""
    global hls_segments, hls_seq, hls_discontinuities
    try:
        with hls_lock:
            ts_files = [f for f in os.listdir(HLS_DIR) if f.endswith(".ts")]
            ts_files.sort()
            segments = []
            for idx, fname in enumerate(ts_files):
                if os.path.exists(os.path.join(HLS_DIR, fname)):
                    try:
                        base, suffix = fname.rsplit("_", 1)
                        base_seq = int(base.split("_")[-1])
                        idx_seq = int(suffix.replace(".ts", ""))
                        seq = base_seq + idx_seq
                    except Exception:
                        seq = idx
                    segments.append((seq, fname, 0.0))
            if segments:
                hls_segments = segments
                hls_discontinuities = set()
                hls_seq = hls_segments[-1][0] + 1
    except Exception as e:
        logger.error(f"Rebuild HLS from filesystem failed: {e}")


def reset_hls():
    """Réinitialise complètement le buffer HLS (segments + playlist)."""
    global hls_segments, hls_seq, hls_discontinuities, hls_added_videos
    with hls_lock:
        hls_segments = []
        hls_discontinuities = set()
        hls_seq = 0
        hls_added_videos = set()  # Réinitialiser aussi la liste des vidéos ajoutées
        try:
            if os.path.isdir(HLS_DIR):
                for fn in os.listdir(HLS_DIR):
                    try:
                        os.remove(os.path.join(HLS_DIR, fn))
                    except Exception:
                        pass
        except Exception:
            pass
        # Réécrire la playlist vide après le nettoyage
        write_hls_playlist()


def write_hls_playlist():
    """Réécrit la playlist HLS à partir des segments connus."""
    global hls_segments, hls_discontinuities
    with hls_lock:
        # Nettoyer les entrées dont le fichier n'existe plus
        hls_segments = sorted(
            [(seq, fname, dur) for (seq, fname, dur) in hls_segments if os.path.exists(os.path.join(HLS_DIR, fname))],
            key=lambda x: x[0]
        )
        if not hls_segments:
            hls_discontinuities.clear()
            # Écrire une playlist vide valide pour nettoyer le fichier m3u8
            lines = [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                "#EXT-X-TARGETDURATION:1",
                "#EXT-X-MEDIA-SEQUENCE:0",
                "#EXT-X-ENDLIST"
            ]
            with open(HLS_PLAYLIST, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return

        valid_seqs = {seq for (seq, _, _) in hls_segments}
        # Ne pas marquer la première entrée comme discontinuité
        first_seq = hls_segments[0][0]
        hls_discontinuities = {seq for seq in hls_discontinuities if seq in valid_seqs and seq != first_seq}

        target = max(1, math.ceil(max(seg[2] for seg in hls_segments)))
        media_seq = hls_segments[0][0]
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            "#EXT-X-INDEPENDENT-SEGMENTS",
            f"#EXT-X-TARGETDURATION:{target}",
            f"#EXT-X-MEDIA-SEQUENCE:{media_seq}",
        ]
        for seq, fname, dur in hls_segments:
            if seq in hls_discontinuities:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.append(f"#EXTINF:{dur:.3f},")
            lines.append(fname)
        # Ajouter #EXT-X-ENDLIST pour permettre la boucle dans le lecteur web
        # mpv avec --loop-playlist=inf rechargera la playlist périodiquement
        lines.append("#EXT-X-ENDLIST")
        with open(HLS_PLAYLIST, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def _get_video_duration(video_path: str) -> float:
    """Obtient la durée d'une vidéo en secondes en utilisant ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", 
             "-of", "default=nokey=1:noprint_wrappers=1", video_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            dur = float(result.stdout.strip())
            return dur if dur > 0 else 0.0
    except Exception as e:
        logger.debug(f"Erreur lors de la détection de durée: {e}")
    return 0.0

def append_clip_to_hls(video_path: str, segment_time: Optional[int] = None):
    """Segmenter un clip en TS et l'ajouter à la playlist live.
    
    Si segment_time n'est pas spécifié, la durée est calculée automatiquement
    en fonction de la durée totale du clip pour optimiser la taille des segments.
    """
    global hls_seq, hls_segments, hls_discontinuities, hls_added_videos
    if not os.path.exists(video_path):
        logger.warning(f"append_clip_to_hls: Fichier vidéo introuvable: {video_path}")
        # Essayer avec un chemin absolu
        video_path_abs = os.path.abspath(video_path)
        if os.path.exists(video_path_abs):
            logger.info(f"append_clip_to_hls: Fichier trouvé avec chemin absolu: {video_path_abs}")
            video_path = video_path_abs
        else:
            logger.error(f"append_clip_to_hls: Fichier introuvable même avec chemin absolu: {video_path_abs}")
            return
    
    # Normaliser le chemin pour la comparaison
    video_path_normalized = os.path.abspath(video_path)
    
    # Vérifier si ce fichier a déjà été ajouté à la playlist HLS
    try:
        file_size = os.path.getsize(video_path_normalized)
        video_id = (video_path_normalized, file_size)
        
        with hls_lock:
            if video_id in hls_added_videos:
                logger.info(f"append_clip_to_hls: Fichier déjà présent dans la playlist HLS, ignoré: {video_path_normalized}")
                return
    except Exception as e:
        logger.warning(f"append_clip_to_hls: Impossible de vérifier la taille du fichier: {e}")
        # En cas d'erreur, utiliser seulement le chemin
        video_id = (video_path_normalized, None)
        with hls_lock:
            # Vérifier si le chemin existe déjà (sans la taille)
            existing_paths = {path for path, _ in hls_added_videos if path == video_path_normalized}
            if existing_paths:
                logger.info(f"append_clip_to_hls: Fichier déjà présent dans la playlist HLS, ignoré: {video_path_normalized}")
                return

    # Si segment_time n'est pas spécifié, le calculer automatiquement
    if segment_time is None:
        video_duration = _get_video_duration(video_path)
        if video_duration > 0:
            # Adapter la taille des segments en fonction de la durée du clip
            # Clips courts (< 10s) : segments de 2s
            # Clips moyens (10-30s) : segments de 3s
            # Clips longs (> 30s) : segments de 4s
            if video_duration < 10:
                segment_time = 2
            elif video_duration < 30:
                segment_time = 3
            else:
                segment_time = 4
        else:
            # Durée inconnue, utiliser la valeur par défaut
            segment_time = 4
        logger.debug(f"Durée du clip: {video_duration:.2f}s, taille de segment choisie: {segment_time}s")

    with hls_lock:
        had_existing_segments = bool(hls_segments)
        tmp_dir = tempfile.mkdtemp(prefix="hls_seg_")
        start_number = hls_seq
        unique_prefix = f"seg_{int(time.time() * 1000)}_{start_number:010d}"
        segment_pattern = os.path.join(tmp_dir, f"{unique_prefix}_%03d.ts")
        playlist_tmp = os.path.join(tmp_dir, "playlist.m3u8")
        gop_size = max(30, int(segment_time * 30))
        keyint_min = max(15, gop_size // 2)
        force_key_expr = f"expr:gte(t,n_forced*{segment_time})"
        # La rotation est gérée par mpv, pas besoin de l'encoder dans les segments
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "main",
            "-crf",
            "21",
            "-g",
            str(gop_size),
            "-keyint_min",
            str(keyint_min),
            "-sc_threshold",
            "0",
            "-force_key_frames",
            force_key_expr,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-reset_timestamps",
            "1",
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
            logger.info(f"Segmentation HLS en cours pour: {video_path}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            logger.info(f"Segmentation HLS réussie pour: {video_path}")
        except subprocess.TimeoutExpired:
            logger.error(f"Segmentation HLS timeout pour: {video_path}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        except subprocess.CalledProcessError as e:
            logger.error(f"Segmentation HLS échouée pour {video_path}: {e}")
            logger.error(f"stderr: {e.stderr[:500] if e.stderr else 'N/A'}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        except Exception as e:
            logger.error(f"Segmentation HLS échouée (exception): {e}", exc_info=True)
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
        if new_segments:
            if had_existing_segments:
                hls_discontinuities.add(new_segments[0][0])
            
            # Éviter les segments dupliqués en vérifiant les séquences existantes
            existing_seqs = {seq for (seq, _, _) in hls_segments}
            for seg in new_segments:
                seq, fname, dur = seg
                if seq not in existing_seqs:
                    hls_segments.append(seg)
                    existing_seqs.add(seq)
                else:
                    logger.warning(f"Duplicate segment sequence {seq} for {fname}, skipping")
            
            # Marquer ce fichier vidéo comme ajouté à la playlist
            try:
                file_size = os.path.getsize(video_path_normalized)
                video_id = (video_path_normalized, file_size)
                hls_added_videos.add(video_id)
                logger.debug(f"append_clip_to_hls: Fichier marqué comme ajouté: {video_path_normalized} ({file_size} bytes)")
            except Exception as e:
                logger.warning(f"append_clip_to_hls: Impossible de marquer le fichier comme ajouté: {e}")
            
            # Trier par séquence pour garantir l'ordre
            hls_segments.sort(key=lambda x: x[0])
            hls_seq = hls_segments[-1][0] + 1

        # Garder seulement les segments récents
        if len(hls_segments) > HLS_MAX_SEGMENTS:
            to_remove = hls_segments[:-HLS_MAX_SEGMENTS]
            hls_segments = hls_segments[-HLS_MAX_SEGMENTS:]
            for _, fname, _ in to_remove:
                try:
                    os.remove(os.path.join(HLS_DIR, fname))
                except Exception:
                    pass
            # Nettoyer la liste des vidéos ajoutées pour les fichiers qui ne sont plus dans la playlist
            # (on garde seulement les vidéos qui sont encore présentes)
            remaining_paths = set()
            for seq, fname, _ in hls_segments:
                # Les segments sont dans HLS_DIR, on ne peut pas directement retrouver le fichier source
                # Mais on peut nettoyer les entrées pour les fichiers qui n'existent plus
                pass
            # Nettoyer les entrées pour les fichiers qui n'existent plus
            hls_added_videos = {
                (path, size) for (path, size) in hls_added_videos 
                if os.path.exists(path)
            }

        # Nettoyer les entrées dont le fichier a disparu
        hls_segments = [(seq, fname, dur) for (seq, fname, dur) in hls_segments if os.path.exists(os.path.join(HLS_DIR, fname))]
        if hls_segments:
            valid_seqs = {seq for (seq, _, _) in hls_segments}
            first_seq = hls_segments[0][0]
            hls_discontinuities = {seq for seq in hls_discontinuities if seq in valid_seqs and seq != first_seq}

        write_hls_playlist()

        # Supprimer la vidéo intermédiaire si ce n'est pas un fichier d'upload
        # Ne pas supprimer les fichiers qui sont encore dans le batch
        try:
            uploads_dir = os.path.abspath("uploads")
            video_abs = os.path.abspath(video_path)
            if os.path.exists(video_abs) and not video_abs.startswith(uploads_dir):
                # Vérifier si le fichier est encore utilisé dans le batch
                if not batch_manager.is_file_in_batch(video_abs):
                    os.remove(video_abs)
        except Exception as e:
            logger.debug(f"Cleanup intermédiaire ignoré: {e}")

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

def hls_segments_grouped_by_video():
    """Retourne les segments HLS groupés par vidéo."""
    # Reconstruire à chaque requête pour refléter l'état disque et dédupliquer
    if os.path.exists(HLS_PLAYLIST):
        rebuild_hls_from_playlist()
    elif not hls_segments:
        rebuild_hls_from_filesystem()
    write_hls_playlist()
    
    with hls_lock:
        if not hls_segments:
            return []
        
        # Grouper les segments par vidéo en utilisant les discontinuités
        video_groups = []
        current_group = []
        video_id = 0
        
        for i, (seq, fname, dur) in enumerate(hls_segments):
            # Si c'est une discontinuité (sauf la première), commencer un nouveau groupe
            if seq in hls_discontinuities and current_group:
                video_groups.append({
                    "video_id": video_id,
                    "segments": current_group,
                    "total_duration": sum(s["duration"] for s in current_group),
                    "first_seq": current_group[0]["seq"],
                    "last_seq": current_group[-1]["seq"]
                })
                video_id += 1
                current_group = []
            
            current_group.append({
                "seq": seq,
                "filename": fname,
                "duration": dur,
                "exists": os.path.exists(os.path.join(HLS_DIR, fname))
            })
        
        # Ajouter le dernier groupe
        if current_group:
            video_groups.append({
                "video_id": video_id,
                "segments": current_group,
                "total_duration": sum(s["duration"] for s in current_group),
                "first_seq": current_group[0]["seq"],
                "last_seq": current_group[-1]["seq"]
            })
        
        return video_groups

def delete_hls_segment(seq: int):
    """Supprime un segment HLS par séquence."""
    global hls_segments, hls_discontinuities
    with hls_lock:
        to_delete = [fname for (s, fname, _) in hls_segments if s == seq]
        hls_segments = [(s, fname, dur) for (s, fname, dur) in hls_segments if s != seq]
        hls_discontinuities.discard(seq)
        for fname in to_delete:
            try:
                os.remove(os.path.join(HLS_DIR, fname))
            except Exception:
                pass
        write_hls_playlist()

def delete_hls_video(video_id: int):
    """Supprime tous les segments d'une vidéo par son ID."""
    global hls_segments, hls_discontinuities
    with hls_lock:
        # Reconstruire l'état si nécessaire
        if os.path.exists(HLS_PLAYLIST):
            rebuild_hls_from_playlist()
        elif not hls_segments:
            rebuild_hls_from_filesystem()
        
        if not hls_segments:
            return False
        
        # Grouper les segments par vidéo en utilisant les discontinuités
        video_groups = []
        current_group = []
        current_video_id = 0
        
        for i, (seq, fname, dur) in enumerate(hls_segments):
            # Si c'est une discontinuité (sauf la première), commencer un nouveau groupe
            if seq in hls_discontinuities and current_group:
                video_groups.append({
                    "video_id": current_video_id,
                    "segments": current_group,
                    "first_seq": current_group[0]["seq"],
                    "last_seq": current_group[-1]["seq"]
                })
                current_video_id += 1
                current_group = []
            
            current_group.append({
                "seq": seq,
                "filename": fname,
                "duration": dur
            })
        
        # Ajouter le dernier groupe
        if current_group:
            video_groups.append({
                "video_id": current_video_id,
                "segments": current_group,
                "first_seq": current_group[0]["seq"],
                "last_seq": current_group[-1]["seq"]
            })
        
        if video_id < 0 or video_id >= len(video_groups):
            return False
        
        video_group = video_groups[video_id]
        seqs_to_delete = {seg["seq"] for seg in video_group["segments"]}
        
        # Supprimer les fichiers
        to_delete = [fname for (s, fname, _) in hls_segments if s in seqs_to_delete]
        for fname in to_delete:
            try:
                os.remove(os.path.join(HLS_DIR, fname))
            except Exception:
                pass
        
        # Retirer les segments de la liste
        hls_segments = [(s, fname, dur) for (s, fname, dur) in hls_segments if s not in seqs_to_delete]
        
        # Nettoyer les discontinuités
        hls_discontinuities = {seq for seq in hls_discontinuities if seq not in seqs_to_delete}
        
        write_hls_playlist()
        return True


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
    """Nettoie les fichiers temporaires anciens, en évitant ceux en cours d'utilisation."""
    try:
        files = glob.glob(os.path.join("temp_videos", "*.mp4"))
        current_time = time.time()
        removed_count = 0
        
        # Récupérer les fichiers actuellement utilisés
        used_files = set()
        
        # Fichiers utilisés par le streaming service
        if streaming_service.current_video_path and os.path.exists(streaming_service.current_video_path):
            used_files.add(os.path.abspath(streaming_service.current_video_path))
        if streaming_service.next_video_url:
            next_path = streaming_service.next_video_url.replace("/videos/", "temp_videos/")
            if os.path.exists(next_path):
                used_files.add(os.path.abspath(next_path))
        
        # Fichiers utilisés par le batch manager
        with batch_manager.lock:
            for clip in batch_manager.current_batch:
                if clip.get("path") and os.path.exists(clip["path"]):
                    used_files.add(os.path.abspath(clip["path"]))
            for clip in batch_manager.next_batch:
                if clip.get("path") and os.path.exists(clip["path"]):
                    used_files.add(os.path.abspath(clip["path"]))
        
        # Trier par date de modification
        files_with_time = [(f, os.path.getmtime(f)) for f in files]
        files_with_time.sort(key=lambda x: x[1])
        
        for filepath, mtime in files_with_time:
            file_abs = os.path.abspath(filepath)
            
            # Ne pas supprimer si le fichier est en cours d'utilisation
            if file_abs in used_files:
                logger.debug(f"Skipping cleanup of active file: {os.path.basename(filepath)}")
                continue
            
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
        
        # Nettoyer l'historique des fichiers supprimés
        cleanup_history()
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


def note_hls_access():
    """Marque un accès récent au flux HLS (playlist ou segment)."""
    global last_hls_access_ts
    with hls_access_lock:
        last_hls_access_ts = time.time()


def has_recent_hls_viewer(window_seconds: float = 30.0) -> bool:
    """Indique s'il y a eu un accès HLS récent (mpv, player externe)."""
    with hls_access_lock:
        if last_hls_access_ts <= 0:
            return False
        return (time.time() - last_hls_access_ts) < window_seconds

# Routes API pour preview (doivent être définies AVANT le mount)
@app.get("/preview/progress")
async def get_preview_progress():
    """Retourne l'état de progression courant pour la prévisualisation."""
    with preview_progress_lock:
        return dict(preview_progress_state)

@app.post("/preview/generate")
async def generate_preview(settings: Settings):
    """Génère un clip pour prévisualisation sans impacter la diffusion.
    Utilise les settings fournis dans le body (sans les sauvegarder)."""
    try:
        # Réinitialiser l'état de progression
        set_preview_progress("preparing", 0, "Démarrage de la prévisualisation...")
        
        # Générer le clip en arrière-plan avec les settings fournis (sans les sauvegarder)
        # Les settings ne remplacent pas current_settings, ils sont utilisés uniquement pour cette prévisualisation
        loop = asyncio.get_event_loop()
        result_url = await loop.run_in_executor(None, generate_preview_clip_sync, settings)
        
        return {"status": "success", "url": result_url}
    except Exception as e:
        logger.error(f"Preview generation error: {e}", exc_info=True)
        set_preview_progress("error", 0, f"Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files (après les routes API)
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
app.mount("/videos", StaticFiles(directory="temp_videos"), name="videos")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/exports", StaticFiles(directory="exports"), name="exports")
app.mount("/preview", StaticFiles(directory=preview_videos_dir), name="preview")
app.mount("/stream", StaticFiles(directory=HLS_DIR), name="stream")


def _purge_directory(dir_path: str, allow_dirs: bool = False) -> int:
    """Delete files (and optionally directories) within dir_path. Returns count removed."""
    if not os.path.isdir(dir_path):
        return 0
    removed = 0
    for name in os.listdir(dir_path):
        full = os.path.join(dir_path, name)
        try:
            if os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
                removed += 1
            elif allow_dirs and os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
        except Exception as e:
            logger.warning(f"Failed to delete {full}: {e}")
    return removed


@app.middleware("http")
async def hls_access_middleware(request, call_next):
    # Si la requête cible le flux HLS (playlist ou segments), on note l'accès.
    path = request.url.path or ""
    if path.startswith("/stream/"):
        note_hls_access()
        # Quand le manifest est demandé, on régénère la playlist pour purger les
        # entrées dont les fichiers auraient été supprimés (évite les msn fantômes).
        if path.endswith(".m3u8"):
            try:
                hls_segments_state()
            except Exception as e:
                logger.warning(f"Rebuild HLS playlist on access failed: {e}")
    response = await call_next(request)
    return response

async def generate_initial_batch():
    """Génère le batch initial en arrière-plan après le démarrage de l'API."""
    # Attendre un peu pour s'assurer que l'API est complètement démarrée
    await asyncio.sleep(2)
    
    logger.info("Génération du batch initial en arrière-plan...")
    for i in range(current_settings.batch_size):
        logger.info(f"Génération clip {i+1}/{current_settings.batch_size} du batch initial...")
        try:
            await generate_next_clip_async(batch_fill=True)
            # Attendre un peu entre chaque génération pour éviter la surcharge
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Erreur lors de la génération du clip {i+1}: {e}")
    logger.info(f"Batch initial généré ({len(batch_manager.next_batch)}/{current_settings.batch_size} clips)")

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
    
    # Démarrer la boucle de génération automatique
    asyncio.create_task(streaming_loop())
    
    # Générer le batch initial en arrière-plan (ne bloque pas le démarrage de l'API)
    asyncio.create_task(generate_initial_batch())

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
    files = glob.glob(os.path.join("temp_videos", "complete_*.mp4"))
    if not files:
        # Fallback pour les anciens fichiers sans préfixe
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


def _ensure_node_ids(effect_chain: List[Dict[str, Any]]):
    for entry in effect_chain:
        if not entry.get("id"):
            entry["id"] = str(uuid.uuid4())


def _fill_default_options(effect_chain: List[Dict[str, Any]]):
    for entry in effect_chain:
        name = entry.get("name")
        defaults = effect_manager.get_default_options_for_effect(name)
        opts = entry.get("options", {}) or {}
        for k, v in defaults.items():
            opts.setdefault(k, v)
        entry["options"] = opts


def _fallback_sequential_inputs(effect_chain: List[Dict[str, Any]]):
    """Create sane defaults for missing inputs (sequential fallback)."""
    for idx, entry in enumerate(effect_chain):
        if entry.get("inputs") is None:
            entry["inputs"] = []
        if entry.get("name") in ("source", "source-local"):
            entry["inputs"] = []
            continue
        if not entry["inputs"] and idx > 0:
            # fallback to previous node output
            entry["inputs"] = [effect_chain[idx - 1]["id"]]


def _select_random_video_from_search(videos, query, include_reels=True, exclude_video_ids=None):
    """
    Sélectionne une vidéo aléatoire parmi les résultats de recherche,
    en excluant celles déjà utilisées avec succès et celles qui ont échoué pour cette requête.
    Si toutes les vidéos ont été utilisées, réinitialise la liste.
    
    Args:
        videos: Liste des vidéos disponibles
        query: Requête de recherche
        include_reels: Inclure les reels
        exclude_video_ids: Liste d'IDs de vidéos à exclure (pour éviter de réessayer les mêmes)
    """
    global youtube_search_used_videos, youtube_search_failed_videos
    if not videos:
        return None
    
    # Filtrer les vidéos valides
    valid = [v for v in videos if v.get("duration")]
    if not include_reels:
        valid = [v for v in valid if not _is_reel(v)]
    
    if not valid:
        return None
    
    # Normaliser la requête pour le cache (lowercase, strip)
    query_key = query.lower().strip()
    
    # Convertir exclude_video_ids en set pour une recherche plus rapide
    exclude_set = set(exclude_video_ids) if exclude_video_ids else set()
    
    with youtube_search_lock:
        # Récupérer les IDs déjà utilisés avec succès pour cette requête
        used_ids = set(youtube_search_used_videos.get(query_key, []))
        # Récupérer les IDs qui ont échoué
        failed_ids = set(youtube_search_failed_videos.get(query_key, []))
        
        # Extraire les IDs des vidéos valides
        valid_ids = {v.get("id") or v.get("url") or v.get("webpage_url"): v for v in valid}
        
        # Filtrer les vidéos non encore utilisées avec succès, non échouées, et pas celles à exclure
        available_videos = [
            v for vid_id, v in valid_ids.items() 
            if vid_id not in used_ids 
            and vid_id not in failed_ids
            and vid_id not in exclude_set
        ]
        
        # Si toutes les vidéos ont été utilisées ou ont échoué, réinitialiser et utiliser toutes les vidéos
        if not available_videos:
            logger.debug(f"Toutes les vidéos ont été utilisées/échouées pour '{query}', réinitialisation")
            available_videos = [v for vid_id, v in valid_ids.items() if vid_id not in exclude_set]
            if not available_videos:
                # Si même après réinitialisation on n'a rien (à cause de exclude_set), réessayer quand même
                available_videos = valid
            # Réinitialiser les listes
            used_ids = []
            failed_ids = []
        
        if not available_videos:
            return None
        
        # Sélectionner une vidéo aléatoire parmi celles disponibles
        selected = random.choice(available_videos)
        selected_id = selected.get("id") or selected.get("url") or selected.get("webpage_url")
        
        # Ne PAS marquer comme utilisée ici - on le fera seulement si le téléchargement réussit
        logger.debug(f"Sélection vidéo pour '{query}': {selected_id} (utilisées: {len(used_ids)}, échouées: {len(failed_ids)})")
        
        return selected


def _select_video_url(opts, settings, exclude_video_ids=None):
    playlist_url = opts.get("playlist_url") or settings.playlist_url
    include_reels = opts.get("include_reels", settings.include_reels)
    keywords_raw = opts.get("keywords") or settings.keywords or ""
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    
    # Convertir en set pour une recherche plus rapide
    exclude_set = set(exclude_video_ids) if exclude_video_ids else set()
    
    if playlist_url:
        videos = yt_service.get_playlist_videos(playlist_url)
        if videos:
            valid = [v for v in videos if v.get("duration")]
            if not include_reels:
                valid = [v for v in valid if not _is_reel(v)]
            # Exclure les vidéos qui ont échoué
            if exclude_set:
                valid = [
                    v for v in valid 
                    if (v.get("id") or v.get("url") or v.get("webpage_url")) not in exclude_set
                ]
            if valid:
                return random.choice(valid)
    if not keywords:
        keywords = ["glitch art"]
    keyword = random.choice(keywords)
    videos = yt_service.search_videos(keyword)
    if videos:
        return _select_random_video_from_search(videos, keyword, include_reels, exclude_video_ids)
    return None


def _fetch_clip_for_source(entry: Dict[str, Any], settings: Settings) -> str:
    opts = entry.get("options", {}) or {}
    duration_base = opts.get("duration", settings.duration)
    duration_var = opts.get("duration_variation", settings.duration_variation)
    duration = duration_base + random.randint(-duration_var, duration_var)
    if duration < 1:
        duration = 1
    video_quality = opts.get("video_quality", settings.video_quality)
    include_reels = opts.get("include_reels", settings.include_reels)
    opts.setdefault("include_reels", include_reels)

    local_file = opts.get("local_file") or settings.local_file
    if entry.get("name") == "source-local" and local_file:
        candidate = os.path.join("uploads", local_file)
        if os.path.exists(candidate):
            base_name = os.path.basename(local_file)
            if not base_name.startswith("complete_"):
                base_name = f"complete_{base_name}"
            dest = os.path.join("temp_videos", f"complete_local_{entry['id']}_{base_name}")
            shutil.copy(candidate, dest)
            return dest

    # Essayer plusieurs vidéos en cas d'échec (max 3 tentatives avec vidéos différentes)
    max_video_attempts = 3
    failed_video_ids = []  # Garder trace des vidéos qui ont échoué dans cette session
    
    for video_attempt in range(max_video_attempts):
        # Exclure toutes les vidéos qui ont déjà échoué dans cette session
        video = _select_video_url(opts, settings, exclude_video_ids=failed_video_ids if failed_video_ids else None)
        
        if not video:
            if video_attempt < max_video_attempts - 1:
                logger.warning(f"Aucune vidéo trouvée, tentative {video_attempt + 1}/{max_video_attempts}")
                time.sleep(2)
                continue
            raise Exception("No video found for source")
        
        video_url = video.get("url") or video.get("webpage_url")
        video_id = video.get("id") or video_url
        video_duration = int(video.get("duration") or 600)
        start_time = random.randint(0, max(0, video_duration - duration))
        
        logger.info(f"Tentative téléchargement vidéo {video_attempt + 1}/{max_video_attempts}: {video_url}")
        raw_path = yt_service.download_clip(video_url, start_time, duration, video_quality)
        
        if raw_path:
            # Marquer la vidéo comme utilisée avec succès seulement si le téléchargement réussit
            keywords_raw = opts.get("keywords") or settings.keywords or ""
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            if not keywords:
                keywords = ["glitch art"]
            keyword = random.choice(keywords)
            query_key = keyword.lower().strip()
            
            with youtube_search_lock:
                if query_key not in youtube_search_used_videos:
                    youtube_search_used_videos[query_key] = []
                if video_id not in youtube_search_used_videos[query_key]:
                    youtube_search_used_videos[query_key].append(video_id)
                # Retirer de la liste des échecs si elle y était
                if query_key in youtube_search_failed_videos and video_id in youtube_search_failed_videos[query_key]:
                    youtube_search_failed_videos[query_key].remove(video_id)
            
            return raw_path
        
        # Si le téléchargement échoue, marquer cette vidéo comme échouée
        failed_video_ids.append(video_id)
        keywords_raw = opts.get("keywords") or settings.keywords or ""
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        if not keywords:
            keywords = ["glitch art"]
        keyword = random.choice(keywords)
        query_key = keyword.lower().strip()
        
        with youtube_search_lock:
            if query_key not in youtube_search_failed_videos:
                youtube_search_failed_videos[query_key] = []
            if video_id not in youtube_search_failed_videos[query_key]:
                youtube_search_failed_videos[query_key].append(video_id)
        
        # Si le téléchargement échoue, essayer une autre vidéo
        if video_attempt < max_video_attempts - 1:
            logger.warning(f"Échec téléchargement pour {video_url}, essai avec une autre vidéo dans 3s...")
            time.sleep(3)
    
    # Toutes les tentatives ont échoué
    raise Exception(f"Download failed for source after {max_video_attempts} attempts with different videos")


def _process_graph_clip(effect_chain: List[Dict[str, Any]], settings: Settings, current_preset: str = "") -> str:
    logger.info("Graph mode: exécution DAG multi-sources")
    set_progress("processing", 10, "Graphe: préparation", preset=current_preset)
    _ensure_node_ids(effect_chain)
    _fill_default_options(effect_chain)
    _fallback_sequential_inputs(effect_chain)

    by_id = {e["id"]: e for e in effect_chain}
    produced: Dict[str, str] = {}

    def resolve(node_id: str) -> str:
        if node_id in produced:
            return produced[node_id]
        entry = by_id[node_id]
        name = entry.get("name")
        inputs = entry.get("inputs", []) or []

        if name in ("source", "source-local"):
            path = _fetch_clip_for_source(entry, settings)
            set_progress("processing", 20, f"Noeud {name}", preset=current_preset, filename=os.path.basename(path) if path else "", node=name)
            produced[node_id] = path
            return path

        if name == "noise":
            effect = effect_manager.effects.get("noise")
            out_path = os.path.join("temp_videos", f"noise_{node_id}_{int(time.time()*1000)}.mp4")
            if effect:
                effect.update_options(entry.get("options", {}) or {})
                result = effect.apply_file(None, out_path)
                set_progress("processing", 25, "Noeud noise", preset=current_preset, filename=os.path.basename(result) if result else "", node="noise")
                produced[node_id] = result
                return result
            raise Exception("Noise source unavailable")

        if name == "transfer-motion":
            if len(inputs) < 2:
                raise Exception("transfer-motion nécessite deux entrées")
            path_a = resolve(inputs[0])
            path_b = resolve(inputs[1])
            if not os.path.exists(path_a):
                raise Exception(f"Input A does not exist for transfer-motion: {path_a}")
            if not os.path.exists(path_b):
                raise Exception(f"Input B does not exist for transfer-motion: {path_b}")
            effect = effect_manager.effects.get("transfer-motion")
            out_path = os.path.join("temp_videos", f"transfer_{node_id}_{int(time.time()*1000)}.mp4")
            if effect:
                effect.update_options(entry.get("options", {}) or {})
                result = effect.apply_file(path_a, out_path, second_input=path_b)
                if not result or not os.path.exists(result):
                    raise Exception(f"Transfer-motion failed: output file does not exist: {result}")
                set_progress("processing", 40, "Noeud transfer-motion", preset=current_preset, filename=os.path.basename(result) if result else "", node="transfer-motion")
                produced[node_id] = result
                return result
            produced[node_id] = path_a
            return path_a

        if name == "chopper":
            if len(inputs) < 1:
                raise Exception("chopper nécessite au moins une entrée")
            resolved_inputs = [resolve(inp) for inp in inputs if inp]
            if not resolved_inputs:
                raise Exception("chopper: aucune entrée valide")
            # Vérifier que tous les fichiers d'entrée existent
            for inp_path in resolved_inputs:
                if not os.path.exists(inp_path):
                    raise Exception(f"Input file does not exist for chopper: {inp_path}")
            effect = effect_manager.effects.get("chopper")
            out_path = os.path.join("temp_videos", f"chop_{node_id}_{int(time.time()*1000)}.mp4")
            if effect:
                effect.update_options(entry.get("options", {}) or {})
                result = effect.apply_file(resolved_inputs[0], out_path, inputs=resolved_inputs)
                if not result or not os.path.exists(result):
                    raise Exception(f"Chopper failed: output file does not exist: {result}")
                produced[node_id] = result
                return result
            produced[node_id] = resolved_inputs[0]
            return resolved_inputs[0]

        if name == "mix":
            if len(inputs) < 2:
                raise Exception("Mix node requires two inputs")
            path_a = resolve(inputs[0])
            path_b = resolve(inputs[1])
            if not os.path.exists(path_a):
                raise Exception(f"Input A does not exist for mix: {path_a}")
            if not os.path.exists(path_b):
                raise Exception(f"Input B does not exist for mix: {path_b}")
            effect = effect_manager.effects.get("mix")
            out_path = os.path.join("temp_videos", f"mix_{node_id}_{int(time.time()*1000)}.mp4")
            if effect:
                effect.update_options(entry.get("options", {}) or {})
                result = effect.apply_file(path_a, out_path, second_input=path_b)
                if not result or not os.path.exists(result):
                    raise Exception(f"Mix failed: output file does not exist: {result}")
                produced[node_id] = result
                return result
            produced[node_id] = path_a
            return path_a

        # Generic single-input effect
        if not inputs:
            raise Exception(f"Node {name} has no input")
        input_path = resolve(inputs[0])
        if not os.path.exists(input_path):
            raise Exception(f"Input file does not exist for node {name}: {input_path}")
        out_path = os.path.join("temp_videos", f"node_{node_id}_{int(time.time()*1000)}.mp4")
        processed = effect_manager.process_video(
            input_path,
            out_path,
            effect_chain=[entry],
            effect_options=settings.effect_options,
            active_effects_names=[],
        )
        if not processed or not os.path.exists(processed):
            raise Exception(f"Processing failed for node {name}: output file does not exist: {processed}")
        set_progress("processing", 50, f"Noeud {name}", preset=current_preset, filename=os.path.basename(processed) if processed else "", node=name)
        produced[node_id] = processed
        return produced[node_id]

    # Sinks = nodes that are not referenced as inputs
    referenced = set()
    for e in effect_chain:
        for i in e.get("inputs", []) or []:
            referenced.add(i)
    sinks = [e["id"] for e in effect_chain if e["id"] not in referenced]
    if not sinks:
        sinks = [effect_chain[-1]["id"]]

    final_path = resolve(sinks[-1])
    if not os.path.exists(final_path):
        raise Exception("Graph processing failed: output missing")
    # Ensure file resides in temp_videos for static serving
    if not os.path.abspath(final_path).startswith(os.path.abspath("temp_videos")):
        base_name = os.path.basename(final_path)
        if not base_name.startswith("complete_"):
            base_name = f"complete_{base_name}"
        dest = os.path.join("temp_videos", base_name)
        shutil.copy(final_path, dest)
        final_path = dest
    set_progress("ready", 100, "Graphe terminé")
    return f"/videos/{os.path.basename(final_path)}"


def generate_clip_sync(settings: Settings, max_retries=3):
    """Synchronous function to handle the entire clip generation process with retry logic."""
    global last_random_preset_name
    worker_id = f"gen_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating clip with settings: duration={settings.duration}, effects={len(settings.effect_chain)}")
    steps = [
        {"name": "sélection", "percent": 5},
        {"name": "téléchargement", "percent": 0},
        {"name": "effets", "percent": 0},
        {"name": "hls", "percent": 0},
    ]
    current_preset_name = ""
    current_file_name = ""
    set_progress("preparing", 0, "Préparation", steps=steps)
    
    # Enregistrer le worker
    register_worker(worker_id, "generation", "", "")
    
    for attempt in range(max_retries):
        try:
            # Mode graphe : si des entrées explicites sont définies, exécuter le DAG et sortir.
            # Sauf si freestyle / random preset demandent une génération aléatoire.
            if not (settings.freestyle_mode or settings.random_preset_mode):
                if settings.effect_chain and any(e.get("inputs") for e in settings.effect_chain):
                    logger.info("Detection d'un graphe non linéaire, passage en mode DAG")
                    set_progress("processing", 5, "Graphe: préparation", preset=last_random_preset_name or "")
                    result_url = _process_graph_clip(settings.effect_chain[:], settings)
                    set_progress("ready", 100, "Graphe terminé", preset=last_random_preset_name or "")
                    return result_url

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
                keywords = [k.strip() for k in (settings.keywords or "").split(",") if k.strip()]
                if not keywords:
                    keywords = ["glitch art", "vaporwave", "datamosh", "abstract visuals"]
                keyword = random.choice(keywords)
                logger.debug(f"Searching for keyword: {keyword}")
                videos = yt_service.search_videos(keyword)
                if videos:
                    # Filtrer les vidéos valides (durée <= 20 min)
                    valid_videos = [v for v in videos if v.get('duration') and v.get('duration') <= 1200]
                    if not settings.include_reels:
                        valid_videos = [v for v in valid_videos if not _is_reel(v)]
                    logger.debug(f"Found {len(valid_videos)} valid videos from search")
                    if valid_videos:
                        # Utiliser la fonction de sélection randomisée qui évite les doublons
                        video = _select_random_video_from_search(valid_videos, keyword, settings.include_reels)
                        if video:
                            video_url = video.get('url') or video.get('webpage_url')
                        else:
                            logger.warning("No video selected from search results")
                            set_progress("error", 0, "Recherche: aucun résultat")
                    else:
                        logger.warning("No videos <= 20 mins found in search results")
                        set_progress("error", 0, "Recherche: aucun résultat")
                else:
                    logger.warning("No videos found from search")
                    set_progress("error", 0, "Recherche: aucun résultat")
                    
            if not video_url:
                raise Exception("No videos found")

            logger.info(f"Selected video: {video_url}")

            # 2. Determine Duration
            duration = settings.duration + random.randint(-settings.duration_variation, settings.duration_variation)
            if duration < 1: duration = 1
            
            # 3. Download Clip (si pas déjà un fichier local)
            if not raw_path:
                steps[1]["percent"] = 5
                set_progress("downloading", 5, "Téléchargement en cours", preset=current_preset_name or last_random_preset_name or "", steps=steps)
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
                steps[1]["percent"] = 100
                current_file_name = os.path.basename(raw_path)
                set_progress("downloading", 60, "Téléchargement terminé", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
                # Mettre à jour le worker avec le nom du clip
                update_worker(worker_id, clip_name=current_file_name)
            else:
                # Pour les fichiers locaux, extraire un segment si nécessaire
                set_progress("preparing", 10, "Fichier local", preset=current_preset_name or last_random_preset_name or "", filename=os.path.basename(raw_path), steps=steps)
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
                
            # 4. Construire la chaîne d'effets (freestyle / preset aléatoire / chaîne sauvegardée)
            output_filename = f"complete_processed_{os.path.basename(raw_path)}"
            output_path = os.path.join("temp_videos", output_filename)
            
            # Build effect chain
            effect_chain = []

            if settings.freestyle_mode:
                logger.debug("Freestyle mode active: Generating random effect chain")
                effect_chain = effect_manager.generate_random_chain()
                current_preset_name = "freestyle"
            elif settings.random_preset_mode:
                logger.debug("Random Preset mode active: Picking random preset")
                presets = [f[:-5] for f in os.listdir(PRESETS_DIR) if f.endswith(".json")]
                if presets:
                    choices = presets[:]
                    # éviter la répétition si possible
                    if last_random_preset_name in choices and len(choices) > 1:
                        choices = [p for p in choices if p != last_random_preset_name]
                    preset_name = random.choice(choices)
                    last_random_preset_name = preset_name
                    current_preset_name = preset_name
                    logger.debug(f"Selected random preset: {preset_name}")
                    try:
                        with open(os.path.join(PRESETS_DIR, f"{preset_name}.json"), "r", encoding="utf-8") as f:
                            effect_chain = json.load(f)
                        set_progress("processing", 15, "Preset chargé", preset=preset_name)
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
            steps[2]["percent"] = 5
            set_progress("processing", 70, "Encodage/effets", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)

            # 5. Cache: inclure la chaîne réellement utilisée (après random/freestyle/preset)
            cache_enabled = not (settings.random_preset_mode or settings.freestyle_mode or settings.randomize_effects)
            cache_key = hashlib.md5(
                f"{video_url}_{duration}_{settings.video_quality}_{json.dumps(effect_chain, sort_keys=True)}".encode()
            ).hexdigest()
            if cache_enabled:
                with cache_lock:
                    cached_path = video_cache.get(cache_key)
                    if cached_path:
                        cached_abs = os.path.join("temp_videos", os.path.basename(cached_path))
                        if os.path.exists(cached_abs):
                            logger.info(f"Using cached clip (chain-aware): {cached_path}")
                            return cached_path

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
            steps[2]["percent"] = 100
            current_file_name = os.path.basename(processed_path)
            set_progress("processing", 90, "Encodage terminé", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
            # Mettre à jour le worker avec le nom du clip final
            update_worker(worker_id, clip_name=current_file_name)
            
            result_url = f"/videos/{os.path.basename(processed_path)}"
            
            # Ajouter à l'historique (fait automatiquement par le streaming service)
            
            # Mettre en cache
            if cache_enabled:
                with cache_lock:
                    video_cache[cache_key] = result_url
                    # Limiter la taille du cache
                    if len(video_cache) > 100:
                        # Supprimer les entrées les plus anciennes
                        oldest_key = next(iter(video_cache))
                        del video_cache[oldest_key]
            steps[3]["percent"] = 100
            set_progress("ready", 100, "Clip prêt", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
            # Retirer le worker
            unregister_worker(worker_id)
            return result_url
            
        except Exception as e:
            logger.error(f"Error generating clip (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            set_progress("error", 0, f"Erreur: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    
    # Retirer le worker en cas d'échec final
    unregister_worker(worker_id)
    raise Exception(f"Failed to generate clip after {max_retries} attempts")

def generate_preview_clip_sync(settings: Settings, max_retries=3):
    """Génère un clip pour prévisualisation sans impacter la diffusion."""
    global last_random_preset_name
    worker_id = f"preview_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating preview clip with settings: duration={settings.duration}, effects={len(settings.effect_chain)}")
    steps = [
        {"name": "sélection", "percent": 5},
        {"name": "téléchargement", "percent": 0},
        {"name": "effets", "percent": 0},
        {"name": "finalisation", "percent": 0},
    ]
    # Enregistrer le worker
    register_worker(worker_id, "preview", "", "")
    current_preset_name = ""
    current_file_name = ""
    set_preview_progress("preparing", 0, "Préparation", steps=steps)
    
    for attempt in range(max_retries):
        try:
            # Mode graphe : si des entrées explicites sont définies, exécuter le DAG et sortir.
            if not (settings.freestyle_mode or settings.random_preset_mode):
                if settings.effect_chain and any(e.get("inputs") for e in settings.effect_chain):
                    logger.info("Preview: Detection d'un graphe non linéaire, passage en mode DAG")
                    set_preview_progress("processing", 5, "Graphe: préparation", preset=last_random_preset_name or "")
                    result_path = _process_graph_clip_preview(settings.effect_chain[:], settings)
                    set_preview_progress("ready", 100, "Graphe terminé", preset=last_random_preset_name or "")
                    return result_path

            # 1. Select Video Source (même logique que generate_clip_sync)
            video_url = None
            video = None
            raw_path = None
            playlist_entry = None
            
            # Priorité 1: Fichier local uploadé
            if settings.local_file:
                local_file_path = os.path.join("uploads", settings.local_file)
                if os.path.exists(local_file_path):
                    logger.info(f"Preview: Using local file: {settings.local_file}")
                    raw_path = local_file_path
                    video_duration = settings.duration
                else:
                    logger.warning(f"Preview: Local file not found: {settings.local_file}")

            # Priorité 2: Playlist interne
            if not raw_path and not video_url:
                playlist_entry = get_next_playlist_entry()
                if playlist_entry:
                    if playlist_entry.get("local_file"):
                        candidate = os.path.join("uploads", playlist_entry["local_file"])
                        if os.path.exists(candidate):
                            raw_path = candidate
                            logger.info(f"Preview: Using playlist local file: {playlist_entry['local_file']}")
                        else:
                            logger.warning(f"Preview: Playlist file not found: {playlist_entry['local_file']}")
                    elif playlist_entry.get("url"):
                        video_url = playlist_entry["url"]
                        logger.info(f"Preview: Using playlist url: {video_url}")
            
            # Priorité 3: Playlist YouTube
            if not raw_path and settings.playlist_url:
                logger.debug(f"Preview: Checking playlist: {settings.playlist_url}")
                videos = yt_service.get_playlist_videos(settings.playlist_url)
                if videos:
                    valid_videos = [v for v in videos if v.get('duration') and v.get('duration') <= 1200]
                    if not settings.include_reels:
                        valid_videos = [v for v in valid_videos if not _is_reel(v)]
                    logger.debug(f"Preview: Found {len(valid_videos)} valid videos in playlist")
                    if valid_videos:
                        video = random.choice(valid_videos)
                        video_url = video['url']
            
            if not video_url:
                # Fallback to search
                keywords = [k.strip() for k in (settings.keywords or "").split(",") if k.strip()]
                if not keywords:
                    keywords = ["glitch art", "vaporwave", "datamosh", "abstract visuals"]
                keyword = random.choice(keywords)
                logger.debug(f"Preview: Searching for keyword: {keyword}")
                videos = yt_service.search_videos(keyword)
                if videos:
                    # Filtrer les vidéos valides (durée <= 20 min)
                    valid_videos = [v for v in videos if v.get('duration') and v.get('duration') <= 1200]
                    if not settings.include_reels:
                        valid_videos = [v for v in valid_videos if not _is_reel(v)]
                    logger.debug(f"Preview: Found {len(valid_videos)} valid videos from search")
                    if valid_videos:
                        # Utiliser la fonction de sélection randomisée qui évite les doublons
                        video = _select_random_video_from_search(valid_videos, keyword, settings.include_reels)
                        if video:
                            video_url = video.get('url') or video.get('webpage_url')
                        else:
                            logger.warning("Preview: No video selected from search results")
                            set_preview_progress("error", 0, "Recherche: aucun résultat")
                    else:
                        logger.warning("Preview: No videos <= 20 mins found in search results")
                        set_preview_progress("error", 0, "Recherche: aucun résultat")
                else:
                    logger.warning("Preview: No videos found from search")
                    set_preview_progress("error", 0, "Recherche: aucun résultat")
                    
            if not video_url:
                raise Exception("No videos found")

            logger.info(f"Preview: Selected video: {video_url}")

            # 2. Determine Duration
            duration = settings.duration + random.randint(-settings.duration_variation, settings.duration_variation)
            if duration < 1: duration = 1
            
            # 3. Download Clip (si pas déjà un fichier local)
            if not raw_path:
                steps[1]["percent"] = 5
                set_preview_progress("downloading", 5, "Téléchargement en cours", preset=current_preset_name or last_random_preset_name or "", steps=steps)
                video_duration = video.get('duration', 600)
                if not video_duration: video_duration = 600
                
                start_time = random.randint(0, max(0, int(video_duration) - duration))
                logger.info(f"Preview: Downloading clip: start={start_time}, duration={duration}")
                
                raw_path = yt_service.download_clip(video_url, start_time, duration, settings.video_quality)
                
                if not raw_path:
                    logger.warning(f"Preview: Download failed for video {video_url}, attempt {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    raise Exception(f"Download failed for video {video_url} after {max_retries} attempts")
                
                logger.info(f"Preview: Download complete: {raw_path}")
                steps[1]["percent"] = 100
                current_file_name = os.path.basename(raw_path)
                set_preview_progress("downloading", 60, "Téléchargement terminé", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
                # Mettre à jour le worker avec le nom du clip
                update_worker(worker_id, clip_name=current_file_name)
            else:
                set_preview_progress("preparing", 10, "Fichier local", preset=current_preset_name or last_random_preset_name or "", filename=os.path.basename(raw_path), steps=steps)
                if settings.duration > 0:
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
                    
                    duration_seconds = settings.duration
                    start_time = 0
                    
                    if duration_seconds < 600:
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
                            pass
            
            # Vérifier que raw_path est défini
            if not raw_path or not os.path.exists(raw_path):
                logger.error(f"Preview: raw_path not defined or file not found: {raw_path}")
                if attempt < max_retries - 1:
                    continue
                raise Exception("No valid video source found for preview")
            
            # 4. Construire la chaîne d'effets
            # S'assurer que le répertoire preview_videos existe
            preview_dir = os.path.join(project_root, "preview_videos")
            os.makedirs(preview_dir, exist_ok=True)
            output_filename = f"preview_{int(time.time() * 1000)}_{os.path.basename(raw_path)}"
            output_path = os.path.join(preview_dir, output_filename)
            
            # Build effect chain (même logique que generate_clip_sync)
            effect_chain = []

            if settings.freestyle_mode:
                logger.debug("Preview: Freestyle mode active")
                effect_chain = effect_manager.generate_random_chain()
                current_preset_name = "freestyle"
            elif settings.random_preset_mode:
                logger.debug("Preview: Random Preset mode active")
                presets = [f[:-5] for f in os.listdir(PRESETS_DIR) if f.endswith(".json")]
                if presets:
                    choices = presets[:]
                    if last_random_preset_name in choices and len(choices) > 1:
                        choices = [p for p in choices if p != last_random_preset_name]
                    preset_name = random.choice(choices)
                    last_random_preset_name = preset_name
                    current_preset_name = preset_name
                    logger.debug(f"Preview: Selected random preset: {preset_name}")
                    try:
                        with open(os.path.join(PRESETS_DIR, f"{preset_name}.json"), "r", encoding="utf-8") as f:
                            effect_chain = json.load(f)
                        set_preview_progress("processing", 15, "Preset chargé", preset=preset_name)
                    except Exception as e:
                        logger.error(f"Preview: Failed to load random preset {preset_name}: {e}")
                else:
                    logger.warning("Preview: No presets found for Random Preset mode")

            if not effect_chain:
                effect_chain = settings.effect_chain[:] if settings.effect_chain else []
                if not effect_chain:
                    for name in settings.active_effects:
                        effect_chain.append({"name": name, "options": settings.effect_options.get(name, {})})
            
            # Mettre à jour le worker avec le preset
            update_worker(worker_id, preset=current_preset_name or last_random_preset_name or "")

            # Fill defaults and optionally randomize
            for entry in effect_chain:
                name = entry.get("name")
                defaults = effect_manager.get_default_options_for_effect(name)
                opts = entry.get("options", {}) or {}
                for k, v in defaults.items():
                    opts.setdefault(k, v)
                entry["options"] = opts

            if settings.randomize_effects:
                logger.debug("Preview: Randomizing effect options")
                for entry in effect_chain:
                    name = entry.get("name")
                    random_opts = effect_manager.get_random_options_for_effect(name)
                    entry_opts = entry.get("options", {}) or {}
                    entry_opts.update(random_opts)
                    entry["options"] = entry_opts

            logger.info(f"Preview: Applying effects chain: {[e.get('name') for e in effect_chain]}")
            steps[2]["percent"] = 5
            set_preview_progress("processing", 70, "Encodage/effets", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)

            processed_path = effect_manager.process_video(
                raw_path,
                output_path,
                effect_chain=effect_chain,
                effect_options=settings.effect_options,
                active_effects_names=settings.active_effects,
            )
            
            if not processed_path or not os.path.exists(processed_path):
                logger.error(f"Preview: Processing failed, output file not found: {processed_path}")
                if attempt < max_retries - 1:
                    continue
                raise Exception("Video processing failed")
            
            logger.info(f"Preview: Processing complete: {processed_path}")
            # Vérifier que le fichier est bien dans preview_videos
            if not processed_path.startswith(preview_videos_dir):
                # Le fichier n'est pas dans preview_videos, le copier
                preview_filename = f"preview_{int(time.time() * 1000)}_{os.path.basename(processed_path)}"
                preview_path = os.path.join(preview_videos_dir, preview_filename)
                logger.info(f"Preview: Copie du fichier vers preview_videos: {preview_path}")
                shutil.copy(processed_path, preview_path)
                if os.path.exists(preview_path):
                    processed_path = preview_path
                    logger.info(f"Preview: Fichier copié avec succès: {preview_path}")
                else:
                    logger.error(f"Preview: Échec de la copie vers preview_videos: {preview_path}")
            
            steps[2]["percent"] = 100
            current_file_name = os.path.basename(processed_path)
            set_preview_progress("processing", 90, "Encodage terminé", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
            # Mettre à jour le worker avec le nom du clip final
            update_worker(worker_id, clip_name=current_file_name)
            
            result_url = f"/preview/{os.path.basename(processed_path)}"
            steps[3]["percent"] = 100
            set_preview_progress("ready", 100, "Clip prêt", preset=current_preset_name or last_random_preset_name or "", filename=current_file_name, steps=steps)
            # Retirer le worker
            unregister_worker(worker_id)
            return result_url
            
        except Exception as e:
            logger.error(f"Preview: Error generating clip (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            set_preview_progress("error", 0, f"Erreur: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    
    # Retirer le worker en cas d'échec final
    unregister_worker(worker_id)
    raise Exception(f"Preview: Failed to generate clip after {max_retries} attempts")

def _process_graph_clip_preview(effect_chain: List[Dict[str, Any]], settings: Settings) -> str:
    """Version prévisualisation de _process_graph_clip qui sauvegarde dans preview_videos."""
    current_preset = last_random_preset_name or ""
    set_preview_progress("processing", 10, "Graphe: préparation", preset=current_preset)
    
    result_url = _process_graph_clip(effect_chain[:], settings)
    video_path = result_url.replace("/videos/", "temp_videos/")
    logger.info(f"Preview: Copie depuis {video_path} vers preview_videos")
    if os.path.exists(video_path):
        preview_dir = os.path.join(project_root, "preview_videos")
        os.makedirs(preview_dir, exist_ok=True)
        preview_filename = f"preview_{int(time.time() * 1000)}_{os.path.basename(video_path)}"
        preview_path = os.path.join(preview_dir, preview_filename)
        logger.info(f"Preview: Copie vers {preview_path}")
        shutil.copy(video_path, preview_path)
        if os.path.exists(preview_path):
            logger.info(f"Preview: Fichier copié avec succès: {preview_path}")
            return f"/preview/{preview_filename}"
        else:
            logger.error(f"Preview: Échec de la copie, fichier non trouvé: {preview_path}")
    else:
        logger.error(f"Preview: Fichier source non trouvé: {video_path}")
    return result_url

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

class BatchManager:
    def __init__(self):
        self.current_batch = [] # List of {"url": str, "duration": float, "path": str}
        self.next_batch = []
        self.current_batch_start_time = 0
        self.current_index = 0
        self.lock = threading.RLock()
    
    def get_next_clip(self, settings: Settings) -> Optional[Dict[str, Any]]:
        with self.lock:
            now = time.time()
            interval_sec = settings.batch_interval * 60
            
            # Should we switch batch?
            # Switch only if next batch is FULL (or sufficient) and time has passed
            if self.next_batch and len(self.next_batch) >= settings.batch_size:
                # If current is empty or time expired
                if not self.current_batch or (now - self.current_batch_start_time > interval_sec):
                     logger.info(f"BatchManager: Switching to NEXT batch (Size: {len(self.next_batch)})")
                     self.current_batch = self.next_batch
                     self.next_batch = []
                     self.current_batch_start_time = now
                     self.current_index = 0
            
            # Bootstrap: if current empty but next has something (even if not full, better than nothing?)
            # The user said "prepare le deuxieme batch... attend Y min". So strict strictness on interval?
            # Let's stick to strict interval, unless current is empty.
            if not self.current_batch and self.next_batch:
                 logger.info("BatchManager: Bootstrapping from next batch")
                 self.current_batch = self.next_batch
                 self.next_batch = []
                 self.current_batch_start_time = now
                 self.current_index = 0
            
            if not self.current_batch:
                return None

            # Return current clip and advance index
            clip = self.current_batch[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.current_batch)
            return clip.copy()

    def add_to_next_batch(self, clip: Dict[str, Any]):
        with self.lock:
            self.next_batch.append(clip)
            logger.info(f"BatchManager: Added clip to NEXT batch ({len(self.next_batch)}/{current_settings.batch_size})")
            
    def needs_generation(self, settings: Settings) -> bool:
        with self.lock:
            return len(self.next_batch) < settings.batch_size

    def is_file_in_batch(self, file_path: str) -> bool:
        """Vérifie si un fichier est encore utilisé dans le batch actuel ou suivant."""
        with self.lock:
            for clip in self.current_batch:
                if clip.get("path") == file_path:
                    return True
            for clip in self.next_batch:
                if clip.get("path") == file_path:
                    return True
            return False

    def reset(self):
        """Réinitialise l'état du batch manager."""
        with self.lock:
            self.current_batch = []
            self.next_batch = []
            self.current_batch_start_time = time.time()
            self.current_index = 0
            logger.info("BatchManager: Reset complete")

    def get_status(self) -> Dict[str, Any]:
        """Retourne l'état actuel du batch (temps restant, tailles, etc.)."""
        with self.lock:
            now = time.time()
            interval_sec = current_settings.batch_interval * 60
            remaining = 0
            if self.current_batch:
                elapsed = now - self.current_batch_start_time
                remaining = max(0, interval_sec - elapsed)
            
            return {
                "active": True,  # Mode batch toujours actif
                "current_size": len(self.current_batch),
                "next_size": len(self.next_batch),
                "target_size": current_settings.batch_size,
                "remaining_seconds": remaining,
                "interval_minutes": current_settings.batch_interval
            }

batch_manager = BatchManager()

async def generate_next_clip_async(force: bool = False, batch_fill: bool = False):
    """Génère le prochain clip pour le streaming (fonction async).
    
    - force=True : génération explicite (même sans clients).
    - batch_fill=True : mode remplissage de batch (ne définit pas next_video du stream).
    """
    global is_generating_next
    
    if is_generating_next:
        return
    
    is_generating_next = True
    loop = asyncio.get_event_loop()
    
    try:
        # En mode batch fill, on génère aveuglément pour remplir le buffer
        if not batch_fill and not force:
            state_snapshot = streaming_service.get_state()
            client_count = streaming_service.client_count()
            has_hls_viewer = has_recent_hls_viewer()
            
            if state_snapshot.get("next_video"):
                logger.debug("Skip génération: next déjà prêt, rien à faire.")
                return {"status": "skipped", "reason": "next_ready"}
            if client_count == 0 and not has_hls_viewer:
                logger.debug("Skip génération: aucun client connecté ni viewer HLS récent.")
                return {"status": "skipped", "reason": "no_clients_or_hls"}

        logger.info(f"Génération du prochain clip (Batch: {batch_fill})...")
        # Générer le clip en arrière-plan
        url = await loop.run_in_executor(None, generate_clip_sync, current_settings)
        repeats_target = 0  # Pas de répétition
        
        # Obtenir la durée du clip
        # Construire le chemin du fichier vidéo
        filename = url.replace("/videos/", "")
        video_path = os.path.join("temp_videos", filename)
        # Utiliser un chemin absolu pour éviter les problèmes de répertoire de travail
        video_path = os.path.abspath(video_path)
        
        # Vérifier si le fichier existe
        if not os.path.exists(video_path):
            logger.warning(f"Fichier vidéo introuvable: {video_path}")
            # Essayer avec le chemin relatif original
            video_path_rel = os.path.join("temp_videos", filename)
            if os.path.exists(video_path_rel):
                video_path = os.path.abspath(video_path_rel)
                logger.info(f"Fichier trouvé avec chemin relatif résolu: {video_path}")
            else:
                logger.error(f"Fichier vidéo introuvable même avec chemin relatif: {video_path_rel}")
        
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
        
        clip_data = {
            "url": url,
            "duration": duration,
            "repeats_target": repeats_target,
            "path": video_path
        }

        if batch_fill:
             batch_manager.add_to_next_batch(clip_data)
             # Ajouter le nouveau clip à la playlist HLS dès qu'il est généré
             try:
                 if os.path.exists(video_path):
                     logger.info(f"Ajout du nouveau clip généré à la playlist HLS: {video_path}")
                     append_clip_to_hls(video_path)
             except Exception as e:
                 logger.error(f"Erreur lors de l'ajout du nouveau clip à HLS: {e}")
             # Vérifier si le batch est maintenant plein pour arrêter la génération
             if not batch_manager.needs_generation(current_settings):
                 logger.info(f"Batch: Le batch suivant est maintenant plein ({len(batch_manager.next_batch)}/{current_settings.batch_size}), arrêt de la génération")
             # Signal qu'un nouveau clip a été généré - les glow seront réinitialisés côté frontend

        return {"url": url, "duration": duration, "status": "ready"}
    except Exception as e:
        logger.error(f"Error generating clip: {e}")
        await asyncio.sleep(5)
        # Ne pas relancer une récursion infinie en cas d'erreur systématique
    finally:
        is_generating_next = False

@app.post("/streaming/generate-next")
async def generate_next_clip_endpoint():
    """Endpoint pour générer manuellement le prochain clip."""
    asyncio.create_task(generate_next_clip_async(force=True))
    return {"status": "generating"}

@app.post("/generation/pause")
async def pause_generation():
    """Met en pause la génération automatique."""
    global generation_paused
    with generation_pause_lock:
        generation_paused = True
    logger.info("Génération automatique mise en pause")
    return {"status": "paused", "paused": True}

@app.post("/generation/resume")
async def resume_generation():
    """Reprend la génération automatique."""
    global generation_paused
    with generation_pause_lock:
        generation_paused = False
    logger.info("Génération automatique reprise")
    return {"status": "resumed", "paused": False}

@app.get("/generation/status")
async def get_generation_status():
    """Retourne l'état de la génération (pause/resume)."""
    with generation_pause_lock:
        return {"paused": generation_paused}

async def streaming_loop():
    """Boucle principale de gestion du streaming."""
    while True:
        try:
            await asyncio.sleep(1)  # Vérifier toutes les secondes
            
            # --- Gestion Batch ---
            # Générer uniquement pour remplir le batch suivant si nécessaire
            # On s'arrête une fois que le batch est plein
            # Vérifier si la génération est en pause
            with generation_pause_lock:
                is_paused = generation_paused
            
            if not is_paused and batch_manager.needs_generation(current_settings) and not is_generating_next:
                logger.debug(f"Batch: Génération nécessaire (next_batch: {len(batch_manager.next_batch)}/{current_settings.batch_size})")
                asyncio.create_task(generate_next_clip_async(batch_fill=True))
            
            client_count = streaming_service.client_count()
            has_hls_viewer = has_recent_hls_viewer()

            # Sans clients WebSocket ni viewer HLS récent, on continue quand même en mode batch
            # pour remplir le buffer en background
            if not streaming_service.is_playing:
                try:
                    await streaming_service.play()
                except Exception as e:
                    logger.error(f"Lecture auto (clients présents/HLS) échouée: {e}")

            repeats_target = 0  # Pas de répétition
            
            # --- Vérification HLS vide + Batch prêt ---
            # Cette vérification doit se faire AVANT de récupérer l'état pour éviter les problèmes de synchronisation
            # Si la liste des segments HLS est vide et que le prochain batch est prêt, on le diffuse immédiatement
            with hls_lock:
                hls_segments_empty = len(hls_segments) == 0
            with batch_manager.lock:
                next_batch_ready = len(batch_manager.next_batch) >= current_settings.batch_size
            
            if hls_segments_empty and next_batch_ready:
                    logger.info("HLS vide et batch prêt: basculement immédiat vers le prochain batch")
                    # Forcer le basculement vers le prochain batch
                    now = time.time()
                    with batch_manager.lock:
                        if batch_manager.next_batch:
                            batch_manager.current_batch = batch_manager.next_batch
                            batch_manager.next_batch = []
                            batch_manager.current_batch_start_time = now
                            batch_manager.current_index = 0
                            logger.info(f"Batch basculé immédiatement (Size: {len(batch_manager.current_batch)})")
                    
                    # Récupérer le premier clip du batch en utilisant get_next_clip pour avancer l'index
                    first_clip = batch_manager.get_next_clip(current_settings)
                    
                    # Injecter le premier clip du batch dans le flux
                    # Note: Le clip a déjà été ajouté à HLS lors de sa génération, pas besoin de le réajouter
                    if first_clip:
                        # Recharger l'état après le basculement
                        current_state = streaming_service.get_state()
                        # Si pas de vidéo actuelle, on la définit
                        if not current_state["current_video"]:
                            try:
                                streaming_service.set_current_video(
                                    first_clip["url"], 
                                    first_clip["duration"], 
                                    repeats_target=repeats_target, 
                                    path=first_clip["path"]
                                )
                                logger.info(f"Premier clip du batch défini comme current_video: {first_clip['url']}")
                            except Exception as e:
                                logger.error(f"Erreur injection premier clip batch: {e}", exc_info=True)
                        # Sinon, on le met comme next_video
                        elif not current_state["next_video"]:
                            try:
                                streaming_service.set_next_video(first_clip["url"])
                                logger.info(f"Premier clip du batch mis comme next_video: {first_clip['url']}")
                            except Exception as e:
                                logger.error(f"Erreur injection next_video batch: {e}", exc_info=True)
            
            # Récupérer l'état après le basculement potentiel
            state = streaming_service.get_state()
            
            # --- Injection Next Video ---
            if not state["next_video"]:
                 # Essayer de récupérer le prochain clip du batch
                 batch_clip = batch_manager.get_next_clip(current_settings)
                 if batch_clip:
                      # On l'injecte comme next_video
                      # Note: Le clip a déjà été ajouté à HLS lors de sa génération, pas besoin de le réajouter
                      streaming_service.set_next_video(batch_clip["url"])
            
            if not state["current_video"]:
                # Pas de vidéo actuelle, essayer de récupérer depuis le batch manager
                batch_clip = batch_manager.get_next_clip(current_settings)
                if batch_clip:
                    # On a un clip dans le batch, on l'utilise
                    # Note: Le clip a déjà été ajouté à HLS lors de sa génération, pas besoin de le réajouter
                    streaming_service.set_next_video(batch_clip["url"])
                elif not is_generating_next and batch_manager.needs_generation(current_settings):
                    # Le batch est vide et on peut générer, on génère pour remplir le batch
                    logger.debug("Batch: Bootstrap - génération pour remplir le batch vide")
                    asyncio.create_task(generate_next_clip_async(batch_fill=True))
                # Sinon, on attend que le batch soit rempli
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
                else:
                    # Pas de prochaine vidéo prête, essayer de récupérer le prochain clip du batch
                    batch_clip = batch_manager.get_next_clip(current_settings)
                    if batch_clip and os.path.exists(batch_clip["path"]):
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
                        
                        # On a un clip du batch, l'utiliser
                        # Note: Le clip a déjà été ajouté à HLS lors de sa génération, pas besoin de le réajouter
                        next_video_path = batch_clip["path"]
                        next_duration = batch_clip["duration"]
                        await streaming_service.switch_video(batch_clip["url"], next_duration, repeats_target=repeats_target, path=next_video_path)
                        logger.info(f"Batch: Transition vers clip suivant: {batch_clip['url']}")
                    else:
                        # Pas de clip disponible dans le batch, réinjecter le clip courant
                        # Note: Ne pas réajouter à HLS car le clip est déjà présent
                        streaming_service.note_repeat()
                        logger.info("Batch: Pas de clip disponible, réinjection du clip courant")
                    
                    # Générer la prochaine vidéo si nécessaire pour remplir le batch
                    if not is_generating_next:
                        if batch_manager.needs_generation(current_settings):
                            logger.debug("Batch: Génération pour remplir le batch")
                            asyncio.create_task(generate_next_clip_async(batch_fill=True))
                        # Sinon, le batch est plein, on attend
            
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

@app.get("/progress")
async def get_progress():
    """Retourne l'état de progression courant (génération/encodage)."""
    with progress_lock:
        return dict(progress_state)

@app.get("/logs")
async def get_logs():
    """Retourne un extrait des logs backend récents."""
    with log_lock:
        return {"lines": list(log_buffer)}

@app.get("/workers")
async def get_workers():
    """Retourne la liste des workers actifs avec leurs informations."""
    workers = get_active_workers()
    # Convertir les timestamps en durées
    result = {}
    for worker_id, worker_info in workers.items():
        result[worker_id] = {
            "type": worker_info["type"],
            "clip_name": worker_info["clip_name"],
            "preset": worker_info["preset"],
            "status": worker_info["status"],
            "duration": int(time.time() - worker_info["started_at"])
        }
    return result

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
        filename = f"complete_upload_{timestamp}_{file.filename}"
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

@app.get("/api/stream/segments/grouped")
async def get_hls_segments_grouped():
    """Retourne les segments HLS groupés par vidéo."""
    return hls_segments_grouped_by_video()

@app.post("/api/stream/reset")
async def reset_hls_endpoint():
    """Réinitialise complètement la playlist HLS (segments + playlist)."""
    reset_hls()
    return {"status": "reset"}

@app.delete("/api/stream/segment/{seq}")
async def delete_hls_segment_endpoint(seq: int):
    delete_hls_segment(seq)
    return {"status": "deleted", "seq": seq}

@app.delete("/api/stream/video/{video_id}")
async def delete_hls_video_endpoint(video_id: int):
    """Supprime tous les segments d'une vidéo."""
    success = delete_hls_video(video_id)
    if not success:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"status": "deleted", "video_id": video_id}

@app.get("/api/stream/segment/{seq}/preview.m3u8")
async def get_segment_preview_playlist(seq: int):
    """Génère une mini-playlist HLS pour prévisualiser un segment spécifique."""
    with hls_lock:
        segment = None
        for s, fname, dur in hls_segments:
            if s == seq:
                segment = (s, fname, dur)
                break
        
        if not segment or not os.path.exists(os.path.join(HLS_DIR, segment[1])):
            raise HTTPException(status_code=404, detail="Segment not found")
        
        seq_num, fname, dur = segment
        
        # Créer une mini-playlist HLS pour ce segment unique
        # Utiliser une URL absolue vers /stream/ pour que HLS.js puisse charger le segment
        segment_url = f"/stream/{fname}"
        playlist_content = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:{max(1, math.ceil(dur))}
#EXT-X-MEDIA-SEQUENCE:{seq_num}
#EXTINF:{dur:.3f},
{segment_url}
#EXT-X-ENDLIST
"""
        return Response(content=playlist_content, media_type="application/vnd.apple.mpegurl")

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


@app.post("/cleanup-storage")
async def cleanup_storage():
    """Supprime les fichiers temporaires (temp_videos, hls) et nettoie les jobs/logs."""
    removed = {}
    removed["temp_videos"] = _purge_directory("temp_videos")

    # Utiliser reset_hls() pour nettoyer proprement le HLS
    reset_hls()
    removed["hls"] = _purge_directory(HLS_DIR)
    
    # Reset batch state
    batch_manager.reset()
    
    # Nettoyer les workers terminés ou trop anciens (plus de 1 heure)
    current_time = time.time()
    with workers_lock:
        workers_to_remove = []
        for worker_id, worker_info in list(active_workers.items()):
            # Supprimer les workers terminés ou trop anciens (plus de 1 heure)
            worker_age = current_time - worker_info.get("started_at", 0)
            worker_status = worker_info.get("status", "running")
            
            if (worker_status in ["completed", "error", "failed"] or 
                worker_age > 3600):  # Plus d'1 heure
                workers_to_remove.append(worker_id)
        
        for worker_id in workers_to_remove:
            active_workers.pop(worker_id, None)
        
        removed["workers"] = len(workers_to_remove)
        if removed["workers"] > 0:
            logger.info(f"Nettoyage de {removed['workers']} workers terminés ou anciens")
    
    # Nettoyer les anciens logs (garder seulement les 100 derniers)
    with log_lock:
        if len(log_buffer) > 100:
            # Garder les 100 derniers logs
            logs_to_keep = list(log_buffer)[-100:]
            log_buffer.clear()
            log_buffer.extend(logs_to_keep)
            removed["logs"] = len(log_buffer) - 100
        else:
            removed["logs"] = 0

    logger.info(f"Cleanup storage: {removed}")
    return {"status": "ok", "removed": removed}

@app.post("/cleanup-uploads")
async def cleanup_uploads():
    """Supprime uniquement les fichiers du dossier uploads."""
    removed = _purge_directory("uploads")
    return {"status": "ok", "removed": removed}

@app.post("/kill-generation")
async def kill_generation():
    """Tue tous les processus de génération en cours."""
    global is_generating_next
    is_generating_next = False
    
    # Supprimer tous les workers actifs de la liste
    with workers_lock:
        worker_count = len(active_workers)
        active_workers.clear()
        if worker_count > 0:
            logger.info(f"Suppression de {worker_count} worker(s) de la liste active")
    
    # Note: Les processus subprocess en cours continueront mais ne bloqueront plus
    # la prochaine génération. Pour une vraie interruption, il faudrait stocker
    # les références aux processus et les tuer explicitement.
    logger.info("Génération interrompue par l'utilisateur")
    return {"status": "ok", "message": "Génération interrompue"}

@app.post("/generate-now-reset-timer")
async def generate_now_reset_timer():
    """Génère un clip maintenant et remet le timer du batch à 0."""
    # Remettre le timer à 0
    with batch_manager.lock:
        batch_manager.current_batch_start_time = time.time()
    
    # Générer maintenant
    asyncio.create_task(generate_next_clip_async(force=True, batch_fill=True))
    return {"status": "ok", "message": "Génération lancée, timer remis à 0"}

@app.get("/api/batch/status")
async def get_batch_status():
    """Retourne le statut du gestionnaire de batch."""
    return batch_manager.get_status()

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

def cleanup_history():
    """Nettoie l'historique des clips dont les fichiers n'existent plus."""
    global clip_history
    with history_lock:
        cleaned_history = []
        removed_count = 0
        for clip_info in clip_history:
            url = clip_info.get("url", "")
            if not url:
                continue
            
            # Convertir l'URL en chemin de fichier
            file_path = url.replace("/videos/", "temp_videos/")
            
            # Vérifier si le fichier existe
            if os.path.exists(file_path):
                cleaned_history.append(clip_info)
            else:
                removed_count += 1
                logger.debug(f"Removed history entry for deleted file: {url}")
        
        clip_history = cleaned_history
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} history entries for deleted files")

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
