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
        self.last_request_time = 0
        self.min_delay_between_requests = 3.0  # Délai minimum entre requêtes (secondes) - augmenté pour éviter les blocages
        self.request_count = 0
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        ]
        self.youtube_clients = ['android', 'ios', 'web', 'mweb', 'tv_embedded']
    
    def _get_random_user_agent(self):
        """Retourne un User-Agent aléatoire."""
        return random.choice(self.user_agents)
    
    def _get_random_client(self):
        """Retourne un client YouTube aléatoire."""
        return random.choice(self.youtube_clients)
    
    def _rate_limit(self):
        """Applique un délai entre les requêtes pour éviter les blocages."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # Délai minimum entre requêtes
        if time_since_last < self.min_delay_between_requests:
            sleep_time = self.min_delay_between_requests - time_since_last
            # Ajouter un peu d'aléatoire pour paraître plus naturel
            sleep_time += random.uniform(1.0, 2.5)
            time.sleep(sleep_time)
        
        # Délai plus long tous les 5 requêtes (plus fréquent pour éviter les blocages)
        self.request_count += 1
        if self.request_count % 5 == 0:
            logger.debug("Rate limit: pause après 5 requêtes")
            time.sleep(random.uniform(5, 10))
        
        self.last_request_time = time.time()

    def search_videos(self, query, max_results=50):
        """Search for videos on YouTube by keyword."""
        self._rate_limit()
        logger.info(f"Searching for: {query}")
        attempts = [
            f"ytsearch{max_results}:{query}",
            f"ytsearch20:{query}",
            query
        ]
        
        # Rotation des clients et User-Agents
        client = self._get_random_client()
        user_agent = self._get_random_user_agent()
        
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'noplaylist': True,
            'user_agent': user_agent,
            'extractor_args': {'youtube': {
                'player_client': [client],
                'player_skip': ['webpage', 'configs'],  # Skip certaines étapes pour éviter la détection
            }},
            'socket_timeout': 30,
            'retries': 2,
        }
        
        for url in attempts:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(url, download=False)
                    if result and 'entries' in result:
                        return result['entries']
            except Exception as e:
                logger.error(f"Search error with '{url}': {e}")
                # Changer de client pour la prochaine tentative
                client = self._get_random_client()
                user_agent = self._get_random_user_agent()
                ydl_opts['user_agent'] = user_agent
                ydl_opts['extractor_args'] = {'youtube': {'player_client': [client]}}
                time.sleep(random.uniform(1, 3))
                continue
        return []

    def get_playlist_videos(self, playlist_url):
        """Fetch all videos from a playlist."""
        self._rate_limit()
        logger.info(f"Fetching playlist: {playlist_url}")
        
        client = self._get_random_client()
        user_agent = self._get_random_user_agent()
        
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'user_agent': user_agent,
            'extractor_args': {'youtube': {
                'player_client': [client],
                'player_skip': ['webpage', 'configs'],  # Skip certaines étapes pour éviter la détection
            }},
            'socket_timeout': 30,
            'retries': 2,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(playlist_url, download=False)
                if 'entries' in result:
                    return result['entries']
        except Exception as e:
            logger.error(f"Playlist error: {e}")
            # Retry avec un autre client
            try:
                client = self._get_random_client()
                user_agent = self._get_random_user_agent()
                ydl_opts['user_agent'] = user_agent
                ydl_opts['extractor_args'] = {'youtube': {'player_client': [client]}}
                time.sleep(random.uniform(2, 4))
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(playlist_url, download=False)
                    if 'entries' in result:
                        return result['entries']
            except Exception as e2:
                logger.error(f"Playlist retry error: {e2}")
        return []

    def download_clip(self, video_url, start_time, duration, quality="best", max_retries=3):
        """Download only the requested segment of a video.
        
        Args:
            video_url: URL de la vidéo YouTube
            start_time: Temps de début en secondes
            duration: Durée en secondes
            quality: Qualité vidéo (best, 1080p, 720p, 480p)
            max_retries: Nombre maximum de tentatives en cas d'erreur
        """
        self._cleanup_old_files()
        download_dir = os.path.abspath(self.download_path)
        os.makedirs(download_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        outtmpl = os.path.join(download_dir, f"raw_{timestamp}.%(ext)s")
        expected_path = os.path.join(download_dir, f"raw_{timestamp}.mp4")
        
        logger.info(f"Downloading clip from {video_url} ({start_time}s for {duration}s)")
        
        # Check for ffmpeg (local Windows exe or system PATH)
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
        ffmpeg_path = None
        ffmpeg_dir = None
        
        is_windows = os.name == 'nt' or sys.platform.startswith('win')
        
        if is_windows:
            if os.path.exists(ffmpeg_local_exe):
                ffmpeg_path = ffmpeg_local_exe
                ffmpeg_dir = backend_dir
                logger.debug(f"Using local Windows ffmpeg at {ffmpeg_path}")
            else:
                ffmpeg_system = shutil.which("ffmpeg")
                if ffmpeg_system:
                    ffmpeg_path = ffmpeg_system
                    ffmpeg_dir = os.path.dirname(ffmpeg_system)
                    logger.debug(f"Using system ffmpeg at {ffmpeg_path}")
        else:
            ffmpeg_system = shutil.which("ffmpeg")
            if ffmpeg_system:
                ffmpeg_path = ffmpeg_system
                ffmpeg_dir = os.path.dirname(ffmpeg_system)
                logger.debug(f"Using system ffmpeg at {ffmpeg_path}")
            elif os.path.exists(ffmpeg_local_exe):
                logger.warning("System ffmpeg not found, trying Windows exe (may not work)")
                ffmpeg_path = ffmpeg_local_exe
                ffmpeg_dir = backend_dir
        
        if not ffmpeg_path:
            logger.warning("FFmpeg not found in PATH or local directory")
        
        # Formats plus flexibles avec fallbacks pour éviter les erreurs "format not available"
        quality_map = {
            "best": 'bestvideo[ext=mp4]/bestvideo[ext=webm]/bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio[ext=webm]/best[ext=mp4]/best[ext=webm]/best',
            "1080p": 'bv*[height<=1080][ext=mp4]/bv*[height<=1080][ext=webm]+ba[ext=m4a]/ba[ext=webm]/b[height<=1080][ext=mp4]/b[height<=1080][ext=webm]/best[height<=1080]/best',
            "720p": 'bv*[height<=720][ext=mp4]/bv*[height<=720][ext=webm]+ba[ext=m4a]/ba[ext=webm]/b[height<=720][ext=mp4]/b[height<=720][ext=webm]/best[height<=720]/best',
            "480p": 'bv*[height<=480][ext=mp4]/bv*[height<=480][ext=webm]+ba[ext=m4a]/ba[ext=webm]/b[height<=480][ext=mp4]/b[height<=480][ext=webm]/best[height<=480]/best',
        }
        fmt = quality_map.get(quality, quality_map["best"])

        # Rate limiting avant téléchargement
        self._rate_limit()
        
        # Rotation des clients et User-Agents pour chaque téléchargement
        client = self._get_random_client()
        user_agent = self._get_random_user_agent()

        # Look for cookies.txt
        workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cookies_path = os.path.join(workspace_dir, "cookies.txt")
        if not os.path.exists(cookies_path):
             cookies_path = os.path.join(workspace_dir, "backend", "cookies.txt")

        ydl_opts = {
            'format': fmt,
            'outtmpl': outtmpl,
            'quiet': True,
            'overwrites': True,
            'merge_output_format': 'mp4',
            # Empêcher les téléchargements progressifs trop gros
            'continuedl': False,
            'nopart': True,
            # Workaround for "Sign in to confirm you’re not a bot"
            'extractor_args': {'youtube': {
                'player_client': [client],
                'player_skip': ['webpage', 'configs'],  # Skip certaines étapes pour éviter la détection
            }},
            'user_agent': user_agent,
            # Headers supplémentaires pour paraître plus naturel
            'http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
            },
            # Options pour éviter la détection de bot
            'no_warnings': False,
            'extract_flat': False,
            'skip_unavailable_fragments': True,
            'keep_fragments': False,
            # Timeouts plus longs pour éviter les "Broken pipe"
            'socket_timeout': 60,
            'retries': 3,
            'fragment_retries': 3,
            'file_access_retries': 3,
            'http_chunk_size': 10485760,  # 10MB chunks pour plus de stabilité
            # Éviter les requêtes inutiles
            'no_check_certificate': False,
            'prefer_insecure': False,
            # Forcer la récupération même si le format exact n'est pas disponible
            'format_sort': ['res', 'ext', 'codec:vp9', 'codec:avc1'],
        }
        
        if os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path
            logger.info(f"Using cookies from {cookies_path}")
        
        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = ffmpeg_dir
            # Télécharger uniquement la section demandée (yt-dlp range)
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_time, start_time + duration)])
            ydl_opts['force_keyframes_at_cuts'] = True
        else:
            print("FFmpeg not found, downloading full video (slower)")
            # on limitera ensuite via ffmpeg trim si possible
        
        # Retry en cas d'erreur réseau avec rotation des clients
        for attempt in range(max_retries):
            try:
                # Changer de client et User-Agent à chaque tentative
                if attempt > 0:
                    client = self._get_random_client()
                    user_agent = self._get_random_user_agent()
                    ydl_opts['extractor_args'] = {'youtube': {
                        'player_client': [client],
                        'player_skip': ['webpage', 'configs'],
                    }}
                    ydl_opts['user_agent'] = user_agent
                    if 'http_headers' in ydl_opts:
                        ydl_opts['http_headers']['User-Agent'] = user_agent
                    # Délai progressif entre les tentatives
                    wait_time = random.uniform(3 + attempt * 2, 6 + attempt * 3)
                    logger.info(f"Tentative {attempt + 1}/{max_retries} avec client {client}, attente {wait_time:.1f}s")
                    time.sleep(wait_time)
                else:
                    # Première tentative : s'assurer que les headers sont bien définis
                    if 'http_headers' in ydl_opts:
                        ydl_opts['http_headers']['User-Agent'] = user_agent
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                final_path = expected_path
                if not os.path.exists(final_path):
                    # tenter de retrouver un fichier généré avec une autre extension
                    import glob
                    matches = glob.glob(os.path.join(download_dir, f"raw_{timestamp}.*"))
                    if matches:
                        final_path = matches[0]

                if os.path.exists(final_path):
                    size = os.path.getsize(final_path)
                    if size > 0:
                        logger.info(f"Download successful: {final_path} ({size} bytes)")
                        return final_path
                    else:
                        logger.warning("Download finished but file is empty.")
                        if os.path.exists(final_path):
                            os.remove(final_path)
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2
                            logger.warning(f"Nouvelle tentative dans {wait_time}s (tentative {attempt + 2}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        return None
                else:
                    logger.warning("Download finished but file not found.")
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        logger.warning(f"Nouvelle tentative dans {wait_time}s (tentative {attempt + 2}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    return None
            except Exception as e:
                error_msg = str(e)
                # Détecter les blocages YouTube spécifiques
                is_blocked = any(keyword in error_msg.lower() for keyword in [
                    'sign in', 'bot', 'blocked', '429', 'too many requests',
                    'unavailable', 'private video', 'age-restricted'
                ])
                
                # Détecter les erreurs de format
                is_format_error = 'format is not available' in error_msg.lower() or 'requested format' in error_msg.lower()
                
                if is_format_error:
                    logger.warning(f"Format non disponible, utilisation d'un format plus flexible: {error_msg}")
                    if attempt < max_retries - 1:
                        # Essayer des formats de plus en plus simples à chaque tentative
                        if attempt == 0:
                            # Première tentative: format plus permissif mais toujours avec préférences
                            ydl_opts['format'] = 'bestvideo+bestaudio/best'
                        elif attempt == 1:
                            # Deuxième tentative: juste le meilleur disponible, peu importe le format
                            ydl_opts['format'] = 'best'
                        else:
                            # Dernière tentative: accepter n'importe quel format disponible
                            # Retirer complètement la restriction de format
                            if 'format' in ydl_opts:
                                del ydl_opts['format']
                        
                        # Retirer les restrictions de format trop strictes
                        if 'format_sort' in ydl_opts:
                            del ydl_opts['format_sort']
                        
                        # À partir de la deuxième tentative, être plus flexible sur le format de sortie
                        if attempt >= 1:
                            # Accepter webm, mkv, ou autres formats si mp4 n'est pas disponible
                            ydl_opts['merge_output_format'] = 'mp4'  # On essaie toujours mp4 en priorité
                            # Mais on accepte aussi d'autres extensions dans le template
                            # Le template outtmpl utilise déjà %(ext)s donc ça devrait fonctionner
                        
                        wait_time = random.uniform(2, 4)
                        logger.info(f"Tentative {attempt + 2}/{max_retries} avec format flexible, attente {wait_time:.1f}s")
                        time.sleep(wait_time)
                        continue
                
                if is_blocked:
                    logger.warning(f"Blocage YouTube détecté: {error_msg}")
                    if attempt < max_retries - 1:
                        # Délai plus long en cas de blocage
                        wait_time = random.uniform(15 + attempt * 5, 30 + attempt * 10)
                        logger.warning(f"Attente {wait_time:.1f}s avant nouvelle tentative avec client différent")
                        time.sleep(wait_time)
                        # Changer complètement de client et stratégie
                        client = self._get_random_client()
                        user_agent = self._get_random_user_agent()
                        ydl_opts['extractor_args'] = {'youtube': {
                            'player_client': [client],
                            'player_skip': ['webpage', 'configs'],
                        }}
                        ydl_opts['user_agent'] = user_agent
                        ydl_opts['http_headers']['User-Agent'] = user_agent
                        # Essayer avec un format plus simple en cas de blocage
                        if attempt == max_retries - 2:  # Avant-dernière tentative
                            ydl_opts['format'] = 'best'
                        continue
                
                # Erreurs réseau récupérables
                if "Broken pipe" in error_msg or "Connection" in error_msg or "timeout" in error_msg.lower() or "errno 32" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = random.uniform(3 + attempt * 2, 6 + attempt * 3)
                        logger.warning(f"Erreur réseau ({error_msg}), nouvelle tentative dans {wait_time:.1f}s (tentative {attempt + 2}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                
                # Autres erreurs non récupérables
                logger.error(f"Download error (tentative {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return None
        
        return None
    
    def _trim_video_if_needed(self, final_path, start_time, duration, timestamp, ffmpeg_path, download_dir):
        """Si le fichier reste trop gros ou dépasse la fenêtre demandée, retailler avec ffmpeg (trim)."""
        if os.path.exists(final_path) and ffmpeg_path:
            try:
                trimmed_path = os.path.join(download_dir, f"raw_{timestamp}_trim.mp4")
                subprocess.run([
                    ffmpeg_path, "-y", "-ss", str(start_time), "-i", final_path,
                    "-t", str(duration),
                    "-c", "copy",
                    trimmed_path
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
                    os.remove(final_path)
                    final_path = trimmed_path
            except Exception as e:
                logger.warning(f"Trim fallback failed: {e}")

        return final_path if os.path.exists(final_path) else None

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
