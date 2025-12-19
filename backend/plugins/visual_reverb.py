import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class VisualReverbEffect(VideoEffect):
    def __init__(self):
        self.decay = 0.8
        self.previous_output = None

    @property
    def name(self):
        return "visual_reverb"

    @property
    def description(self):
        return "Creates a feedback loop trail effect"

    @property
    def options(self):
        return [
            {"name": "decay", "type": "float", "default": 0.8, "min": 0.1, "max": 0.99, "label": "Decay", "tooltip": "How much of the previous frame persists"}
        ]

    def update_options(self, options: dict):
        self.decay = options.get("decay", self.decay)

    def reset(self):
        self.previous_output = None

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        if self.previous_output is None:
            self.previous_output = frame.astype(np.float32)
            return frame

        current_float = frame.astype(np.float32)
        
        # Blend current frame with previous output
        # output = current * (1 - decay) + previous * decay
        # Actually, usually reverb is additive or max-blend, but weighted average keeps brightness stable.
        # Let's try weighted average.
        
        # If we want "trails", we want the old stuff to fade out but the new stuff to be fully visible?
        # Standard feedback: new_val = input + old_val * feedback
        # But this explodes brightness.
        # So: new_val = input * (1-feedback) + old_val * feedback
        
        output = cv2.addWeighted(current_float, 1.0 - self.decay, self.previous_output, self.decay, 0)
        
        self.previous_output = output
        
        return output.astype(np.uint8)
