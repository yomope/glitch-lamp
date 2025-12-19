"""
Logging structuré pour l'application Glitch Video Player
"""
import logging
import os
from datetime import datetime
from pathlib import Path

def setup_logger(name: str = "glitch_lamp", log_dir: str = "logs") -> logging.Logger:
    """Configure un logger avec sortie console et fichier."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Éviter les handlers dupliqués
    if logger.handlers:
        return logger
    
    # Format des logs
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler fichier
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

# Logger global
logger = setup_logger()
