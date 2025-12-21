"""
Service de streaming centralisé pour synchroniser la diffusion à tous les clients
"""
import asyncio
import time
import json
from typing import Dict, Set, Optional
from datetime import datetime
from backend.utils.logger import logger

class StreamingService:
    def __init__(self):
        self.current_video_url: Optional[str] = None
        self.current_video_path: Optional[str] = None
        self.current_video_start_time: float = 0.0  # Temps de début de la vidéo actuelle
        self.video_start_timestamp: float = 0.0  # Timestamp Unix du début de lecture
        self.is_playing: bool = True
        self.playback_speed: float = 1.0
        self.connected_clients: Set[any] = set()  # Set de WebSocket connections
        self.lock = asyncio.Lock()
        self.next_video_url: Optional[str] = None
        self.video_duration: float = 0.0
        self.repeat_count: int = 0
        self.repeats_target: int = 0
        
    async def add_client(self, websocket):
        """Ajoute un client connecté."""
        async with self.lock:
            self.connected_clients.add(websocket)
            logger.info(f"Client connecté. Total: {len(self.connected_clients)}")
    
    async def remove_client(self, websocket):
        """Retire un client déconnecté."""
        async with self.lock:
            self.connected_clients.discard(websocket)
            logger.info(f"Client déconnecté. Total: {len(self.connected_clients)}")
    
    async def broadcast(self, message: Dict):
        """Diffuse un message à tous les clients connectés."""
        if not self.connected_clients:
            return
        
        message_json = json.dumps(message)
        disconnected = set()
        
        async with self.lock:
            for client in self.connected_clients:
                try:
                    await client.send_text(message_json)
                except Exception as e:
                    logger.warning(f"Erreur lors de l'envoi à un client: {e}")
                    disconnected.add(client)
            
            # Nettoyer les clients déconnectés
            for client in disconnected:
                self.connected_clients.discard(client)

    def client_count(self) -> int:
        """Retourne le nombre de clients connectés (approx, sans verrou)."""
        return len(self.connected_clients)
    
    def set_current_video(self, url: str, duration: float, repeats_target: int = 0, path: str = ""):
        """Définit la vidéo actuellement diffusée."""
        self.current_video_url = url
        self.current_video_path = path
        self.video_duration = duration
        self.video_start_timestamp = time.time()
        self.current_video_start_time = 0.0
        self.repeats_target = max(0, repeats_target)
        self.repeat_count = 0
        logger.info(f"Nouvelle vidéo diffusée: {url} (durée: {duration}s)")
    
    def set_next_video(self, url: str):
        """Définit la prochaine vidéo à diffuser."""
        self.next_video_url = url
        logger.debug(f"Prochaine vidéo préparée: {url}")
    
    def get_current_position(self) -> float:
        """Calcule la position actuelle de la vidéo en secondes."""
        if not self.current_video_url or not self.is_playing:
            return self.current_video_start_time
        
        elapsed = (time.time() - self.video_start_timestamp) * self.playback_speed
        position = self.current_video_start_time + elapsed
        
        # Si on dépasse la durée, retourner la durée maximale
        if position > self.video_duration:
            return self.video_duration
        
        return position
    
    async def play(self):
        """Met en lecture."""
        if self.is_playing:
            return
        
        self.is_playing = True
        self.video_start_timestamp = time.time() - (self.current_video_start_time / self.playback_speed)
        await self.broadcast({
            "type": "play",
            "timestamp": time.time()
        })
        logger.info("Lecture démarrée")
    
    async def pause(self):
        """Met en pause."""
        if not self.is_playing:
            return
        
        # Sauvegarder la position actuelle
        self.current_video_start_time = self.get_current_position()
        self.is_playing = False
        
        await self.broadcast({
            "type": "pause",
            "position": self.current_video_start_time,
            "timestamp": time.time()
        })
        logger.info(f"Pause à la position {self.current_video_start_time:.2f}s")
    
    async def seek(self, position: float):
        """Change la position de lecture."""
        self.current_video_start_time = max(0.0, min(position, self.video_duration))
        self.video_start_timestamp = time.time()
        
        await self.broadcast({
            "type": "seek",
            "position": self.current_video_start_time,
            "timestamp": time.time()
        })
        logger.info(f"Seek à la position {self.current_video_start_time:.2f}s")
    
    async def set_speed(self, speed: float):
        """Change la vitesse de lecture."""
        # Sauvegarder la position actuelle avant de changer la vitesse
        current_pos = self.get_current_position()
        self.playback_speed = max(0.1, min(speed, 4.0))
        self.current_video_start_time = current_pos
        self.video_start_timestamp = time.time()
        
        await self.broadcast({
            "type": "speed",
            "speed": self.playback_speed,
            "timestamp": time.time()
        })
        logger.info(f"Vitesse changée à {self.playback_speed}x")
    
    async def switch_video(self, url: str, duration: float, repeats_target: int = 0, path: str = ""):
        """Change de vidéo."""
        self.set_current_video(url, duration, repeats_target=repeats_target, path=path)
        # Le « next » vient d'être consommé ; on le réinitialise.
        self.next_video_url = None
        # Réinitialiser la position
        self.current_video_start_time = 0.0
        self.video_start_timestamp = time.time()
        self.is_playing = True
        
        await self.broadcast({
            "type": "video_change",
            "url": url,
            "duration": duration,
            "timestamp": time.time()
        })
        logger.info(f"Changement de vidéo: {url}")
    
    def note_repeat(self):
        """Enregistre une répétition serveur-side (HLS alimenté ailleurs)."""
        self.repeat_count += 1
        self.current_video_start_time = 0.0
        self.video_start_timestamp = time.time()
        self.is_playing = True
        logger.info(f"Répétition {self.repeat_count}/{self.repeats_target} pour {self.current_video_url}")

    def should_repeat(self) -> bool:
        """Indique si la vidéo actuelle doit encore être répétée."""
        return self.repeat_count < self.repeats_target

    def get_state(self) -> Dict:
        """Retourne l'état actuel du streaming."""
        return {
            "current_video": self.current_video_url,
            "position": self.get_current_position(),
            "duration": self.video_duration,
            "is_playing": self.is_playing,
            "playback_speed": self.playback_speed,
            "next_video": self.next_video_url,
            "timestamp": time.time(),
            "repeat_count": self.repeat_count,
            "repeats_target": self.repeats_target
        }

# Instance globale du service de streaming
streaming_service = StreamingService()
