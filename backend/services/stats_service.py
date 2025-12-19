"""
Service de gestion des statistiques de lecture
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, Any
from threading import Lock

class StatsService:
    def __init__(self, stats_file="stats.json"):
        self.stats_file = stats_file
        self.lock = Lock()
        self.stats = self._load_stats()
    
    def _load_stats(self) -> Dict[str, Any]:
        """Charge les statistiques depuis le fichier."""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading stats: {e}")
        
        # Valeurs par défaut
        return {
            "total_clips_played": 0,
            "total_playback_time": 0.0,  # en secondes
            "session_start": datetime.now().isoformat(),
            "last_reset": datetime.now().isoformat(),
            "clips_today": 0,
            "playback_time_today": 0.0
        }
    
    def _save_stats(self):
        """Sauvegarde les statistiques dans le fichier."""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving stats: {e}")
    
    def record_clip_played(self, duration: float):
        """Enregistre qu'un clip a été joué."""
        with self.lock:
            self.stats["total_clips_played"] += 1
            self.stats["total_playback_time"] += duration
            self.stats["clips_today"] += 1
            self.stats["playback_time_today"] += duration
            self._save_stats()
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques actuelles."""
        with self.lock:
            stats = self.stats.copy()
            # Calculer le temps de session
            try:
                session_start = datetime.fromisoformat(stats["session_start"])
                session_duration = (datetime.now() - session_start).total_seconds()
                stats["session_duration"] = session_duration
            except:
                stats["session_duration"] = 0
            
            return stats
    
    def reset_stats(self):
        """Réinitialise les statistiques."""
        with self.lock:
            self.stats = {
                "total_clips_played": 0,
                "total_playback_time": 0.0,
                "session_start": datetime.now().isoformat(),
                "last_reset": datetime.now().isoformat(),
                "clips_today": 0,
                "playback_time_today": 0.0
            }
            self._save_stats()
    
    def format_time(self, seconds: float) -> str:
        """Formate le temps en format lisible."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
