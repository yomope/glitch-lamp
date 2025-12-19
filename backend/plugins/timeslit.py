import cv2
import numpy as np
from collections import deque
from backend.plugins.base import VideoEffect

class TimeslitEffect(VideoEffect):
    def __init__(self):
        self.buffer_size = 60
        self.fixed_bars = False
        self.buffer = deque(maxlen=self.buffer_size) # Store last 60 frames

    @property
    def name(self):
        return "timeslit"

    @property
    def description(self):
        return "Slit-scan time displacement effect"

    @property
    def options(self):
        return [
            {"name": "buffer_size", "type": "int", "default": 60, "min": 10, "max": 200, "label": "Buffer Size (Frames)", "tooltip": "How many past frames to keep for slicing."},
            {"name": "fixed_bars", "type": "bool", "default": False, "label": "Fixed Bar Count", "tooltip": "If on, always use buffer_size bars instead of growing with history."}
        ]

    def update_options(self, options: dict):
        new_size = options.get("buffer_size", self.buffer_size)
        if new_size != self.buffer_size:
            self.buffer_size = new_size
            self.buffer = deque(maxlen=self.buffer_size)
        self.fixed_bars = options.get("fixed_bars", self.fixed_bars)

    def reset(self):
        self.buffer.clear()

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        self.buffer.append(frame.copy())
        
        if not self.fixed_bars and len(self.buffer) < 2:
            return frame
            
        h, w, c = frame.shape
        output = np.zeros_like(frame)
        
        current_buffer_len = len(self.buffer)
        
        if self.fixed_bars:
            num_bars = self.buffer_size
        else:
            num_bars = current_buffer_len
        
        # We want to map x (0..w) to index (0..num_bars-1)
        chunk_size = w // num_bars
        if chunk_size < 1: chunk_size = 1
        
        end_x = 0
        for i in range(num_bars):
            start_x = i * chunk_size
            end_x = start_x + chunk_size
            if start_x >= w: break
            
            # Get frame from buffer
            if self.fixed_bars:
                source_frame = self.buffer[i % current_buffer_len]
            else:
                source_frame = self.buffer[i]
                
            output[:, start_x:end_x] = source_frame[:, start_x:end_x]
            
        # Fill remaining
        if end_x < w:
             if self.fixed_bars:
                 last_idx = (num_bars - 1) % current_buffer_len
                 output[:, end_x:] = self.buffer[last_idx][:, end_x:]
             else:
                 output[:, end_x:] = self.buffer[-1][:, end_x:]
             
        return output
