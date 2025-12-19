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
from datetime import datetime

from backend.services.youtube_service import YouTubeService
from backend.services.effect_manager import EffectManager
from backend.services.stats_service import StatsService
from backend.services.streaming_service import streaming_service
from backend.plugins.base import VideoEffect

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
    screen_orientation: str = "auto"  # auto, portrait, landscape, portrait-left, portrait-right

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
app.mount("/static", StaticFiles(directory="frontend"), name="static")
app.mount("/videos", StaticFiles(directory="temp_videos"), name="videos")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/exports", StaticFiles(directory="exports"), name="exports")

@app.on_event("startup")
async def startup_event():
    import socket
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
    logger.info(f"Frontend available at:")
    logger.info(f"  - Local: http://127.0.0.1:8000/static/index.html")
    logger.info(f"  - Network: http://{local_ip}:8000/static/index.html")
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
    result = await generate_next_clip_async()
    if result:
        return {"url": result["url"]}
    return {"url": None}

async def generate_next_clip_async():
    """Génère le prochain clip pour le streaming (fonction async)."""
    global is_generating_next
    
    if is_generating_next:
        return
    
    is_generating_next = True
    loop = asyncio.get_event_loop()
    
    try:
        logger.info("Génération du prochain clip pour le streaming...")
        # Générer le clip en arrière-plan
        url = await loop.run_in_executor(None, generate_clip_sync, current_settings)
        
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
            streaming_service.set_current_video(url, duration)
            await streaming_service.switch_video(url, duration)
            logger.info(f"Première vidéo diffusée: {url}")
        else:
            # Sinon, la préparer comme prochaine vidéo
            streaming_service.set_next_video(url)
            logger.info(f"Prochaine vidéo préparée: {url}")
        
        return {"url": url, "duration": duration, "status": "ready"}
    except Exception as e:
        logger.error(f"Error generating clip: {e}")
        # Réessayer après un délai
        await asyncio.sleep(5)
        asyncio.create_task(generate_next_clip_async())
    finally:
        is_generating_next = False

@app.post("/streaming/generate-next")
async def generate_next_clip_endpoint():
    """Endpoint pour générer manuellement le prochain clip."""
    asyncio.create_task(generate_next_clip_async())
    return {"status": "generating"}

async def streaming_loop():
    """Boucle principale de gestion du streaming."""
    while True:
        try:
            await asyncio.sleep(1)  # Vérifier toutes les secondes
            
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
                    
                    await streaming_service.switch_video(state["next_video"], next_duration)
                    # Générer la prochaine vidéo en arrière-plan
                    asyncio.create_task(generate_next_clip_async())
                elif not is_generating_next:
                    # Sinon, générer la prochaine vidéo maintenant
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
