import yt_dlp
import random
import os
import sys
import glob
import time
import shutil

# Import logger
try:
    from backend.utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

class YouTubeService:
    def __init__(self, download_path="temp_videos"):
        self.download_path = download_path
        os.makedirs(download_path, exist_ok=True)

    def search_videos(self, query, max_results=50):
        """Search for videos on YouTube by keyword."""
        logger.info(f"Searching for: {query}")
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
            'noplaylist': True,
        }
        try:
            # Add some randomization to the query to get different results
            # But ytsearch doesn't support random sort. 
            # We rely on fetching a larger pool (max_results) and picking randomly from it.
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
                if 'entries' in result:
                    return result['entries']
        except Exception as e:
            logger.error(f"Search error: {e}")
        return []

    def get_playlist_videos(self, playlist_url):
        """Fetch all videos from a playlist."""
        logger.info(f"Fetching playlist: {playlist_url}")
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(playlist_url, download=False)
                if 'entries' in result:
                    return result['entries']
        except Exception as e:
            logger.error(f"Playlist error: {e}")
        return []

    def download_clip(self, video_url, start_time, duration, quality="best"):
        """Download a specific segment of a video."""
        self._cleanup_old_files()
        
        # Unique filename based on timestamp
        timestamp = int(time.time() * 1000)
        output_filename = os.path.join(self.download_path, f"raw_{timestamp}.mp4")
        
        logger.info(f"Downloading clip from {video_url} ({start_time}s for {duration}s)")
        
        # Check for ffmpeg (local Windows exe or system PATH)
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
        ffmpeg_path = None
        ffmpeg_dir = None
        
        # Detect OS: on Windows use .exe, on Linux/Mac prefer system ffmpeg
        is_windows = os.name == 'nt' or sys.platform.startswith('win')
        
        if is_windows:
            # On Windows, check for local ffmpeg.exe first
            if os.path.exists(ffmpeg_local_exe):
                ffmpeg_path = ffmpeg_local_exe
                ffmpeg_dir = backend_dir
                logger.debug(f"Using local Windows ffmpeg at {ffmpeg_path}")
            else:
                # Fallback to system ffmpeg on Windows
                ffmpeg_system = shutil.which("ffmpeg")
                if ffmpeg_system:
                    ffmpeg_path = ffmpeg_system
                    ffmpeg_dir = os.path.dirname(ffmpeg_system)
                    logger.debug(f"Using system ffmpeg at {ffmpeg_path}")
        else:
            # On Linux/Mac, always prefer system ffmpeg
            ffmpeg_system = shutil.which("ffmpeg")
            if ffmpeg_system:
                ffmpeg_path = ffmpeg_system
                ffmpeg_dir = os.path.dirname(ffmpeg_system)
                logger.debug(f"Using system ffmpeg at {ffmpeg_path}")
            elif os.path.exists(ffmpeg_local_exe):
                # Fallback to .exe only if system ffmpeg not found (unlikely to work on Linux)
                logger.warning("System ffmpeg not found, trying Windows exe (may not work)")
                ffmpeg_path = ffmpeg_local_exe
                ffmpeg_dir = backend_dir
        
        if not ffmpeg_path:
            logger.warning("FFmpeg not found in PATH or local directory")
        
        quality_map = {
            "best": 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            "1080p": 'bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]',
            "720p": 'bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]',
            "480p": 'bv*[ext=mp4][height<=480]+ba[ext=m4a]/b[ext=mp4][height<=480]',
        }
        fmt = quality_map.get(quality, quality_map["best"])

        ydl_opts = {
            'format': fmt,
            'outtmpl': output_filename,
            'quiet': True,
            'overwrites': True,
        }
        
        if ffmpeg_path:
            # Set ffmpeg location for yt-dlp
            ydl_opts['ffmpeg_location'] = ffmpeg_dir
            # Enable partial download
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_time, start_time + duration)])
            ydl_opts['force_keyframes_at_cuts'] = True
        else:
            print("FFmpeg not found, downloading full video (slower)")
            ydl_opts['format'] = fmt or 'best[ext=mp4]/best' # Fallback to single file
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            if os.path.exists(output_filename):
                size = os.path.getsize(output_filename)
                if size > 0:
                    logger.info(f"Download successful: {output_filename} ({size} bytes)")
                    return output_filename
                else:
                    logger.warning("Download finished but file is empty.")
                    os.remove(output_filename)
                    return None
            else:
                logger.warning("Download finished but file not found.")
                return None
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

    def _cleanup_old_files(self, max_files=20, max_age_hours=12):
        """Keep the temp folder clean - improved version."""
        try:
            files = glob.glob(os.path.join(self.download_path, "*.mp4"))
            if not files:
                return
            
            current_time = time.time()
            files_with_time = [(f, os.path.getmtime(f)) for f in files]
            files_with_time.sort(key=lambda x: x[1])  # Plus ancien en premier
            
            removed = 0
            for filepath, mtime in files_with_time:
                age_hours = (current_time - mtime) / 3600
                should_remove = False
                
                # Supprimer si trop vieux
                if age_hours > max_age_hours:
                    should_remove = True
                # Ou si trop de fichiers (garder les plus récents)
                elif len(files_with_time) - removed > max_files:
                    should_remove = True
                
                if should_remove:
                    try:
                        os.remove(filepath)
                        removed += 1
                    except Exception as e:
                        pass  # Ignorer les erreurs de suppression
            
            if removed > 0:
                logger.info(f"Cleaned up {removed} old files from temp_videos")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
