from abc import ABC, abstractmethod
import numpy as np

class VideoEffect(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass
    
    @property
    def type(self) -> str:
        """Returns 'frame' or 'file'"""
        return "frame"

    @property
    def options(self) -> list:
        """
        Returns a list of option definitions.
        Example:
        [
            {"name": "intensity", "type": "int", "default": 10, "min": 0, "max": 100, "label": "Intensity"},
            {"name": "mode", "type": "select", "default": "a", "options": ["a", "b"], "label": "Mode"},
            {"name": "active", "type": "bool", "default": True, "label": "Active"}
        ]
        """
        return []

    def update_options(self, options: dict):
        """Updates the effect configuration with user provided options"""
        pass

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        """Override this for frame-level effects"""
        return frame

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        """Override this for file-level effects. Returns path to processed file."""
        return input_path

    def reset(self):
        """Called before processing a new video. Override to clear state."""
        pass
