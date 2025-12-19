import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class AsciiEffect(VideoEffect):
    def __init__(self):
        self.font_scale = 0.5
        self.thickness = 1
        self.color_mode = "color" # color, grayscale, green (matrix)
        self.charset_preset = "standard"
        self.custom_charset = ""
        
        self.presets = {
            "standard": "@%#*+=-:. ",
            "complex": "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,\"^`'. ",
            "minimal": "#+-. ",
            "binary": "01 ",
            "matrix": "0123456789abcdef"
        }

    @property
    def name(self):
        return "ascii"

    @property
    def description(self):
        return "Render video as ASCII art"

    @property
    def options(self):
        return [
            {"name": "font_scale", "type": "float", "default": 0.5, "min": 0.1, "max": 2.0, "step": 0.1, "label": "Font Scale", "tooltip": "Size multiplier for ASCII characters."},
            {"name": "color_mode", "type": "select", "default": "color", "options": ["color", "grayscale", "matrix"], "label": "Color Mode", "tooltip": "Render in full color, grayscale, or green matrix style."},
            {"name": "charset_preset", "type": "select", "default": "standard", "options": list(self.presets.keys()), "label": "Charset Preset", "tooltip": "Choose a predefined character set ordered dark to light."},
            {"name": "custom_charset", "type": "text", "default": "", "label": "Custom Charset (overrides preset)", "tooltip": "Enter your own characters to override the preset order."}
        ]

    def update_options(self, options: dict):
        self.font_scale = float(options.get("font_scale", self.font_scale))
        self.color_mode = options.get("color_mode", self.color_mode)
        self.charset_preset = options.get("charset_preset", self.charset_preset)
        self.custom_charset = options.get("custom_charset", self.custom_charset)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        h, w, c = frame.shape
        
        # Determine charset
        chars = self.custom_charset if self.custom_charset else self.presets.get(self.charset_preset, self.presets["standard"])
        # Ensure chars are sorted from dark to light usually, but here we map brightness 0-255 to index.
        # Standard convention: Darkest (@) to Lightest ( ). 
        # But if we draw on black background, we might want Lightest char for Brightest pixel.
        # Let's assume the charset is ordered from "dense/bright" to "sparse/dark" or vice versa.
        # Usually: @ is dense (bright on black bg?), . is sparse (dark on black bg?).
        # Let's reverse the standard list if we want @ to represent high intensity? 
        # Actually, usually @ takes up more pixels, so it looks "brighter" if drawing white on black.
        # Let's stick to mapping 0-255 to 0-len(chars).
        
        # Calculate cell size based on font scale
        # Base font size approx 10px for scale 0.5?
        # cv2.getTextSize returns size.
        test_char = "A"
        (text_w, text_h), baseline = cv2.getTextSize(test_char, cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, self.thickness)
        
        cell_w = text_w + 2
        cell_h = text_h + 4
        
        # Resize image to grid size
        cols = w // cell_w
        rows = h // cell_h
        
        if cols <= 0 or rows <= 0:
            return frame
            
        small = cv2.resize(frame, (cols, rows), interpolation=cv2.INTER_NEAREST)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        
        # Create output image
        output = np.zeros_like(frame)
        
        len_chars = len(chars)
        
        for i in range(rows):
            for j in range(cols):
                intensity = gray[i, j]
                char_idx = int((intensity / 255) * (len_chars - 1))
                char = chars[char_idx]
                
                x = j * cell_w
                y = i * cell_h + text_h # Text origin is bottom-left
                
                color = (255, 255, 255)
                if self.color_mode == "color":
                    color = small[i, j].tolist() # BGR
                elif self.color_mode == "matrix":
                    color = (0, 255, 0) # Green
                
                cv2.putText(output, char, (x, y), cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, color, self.thickness)
                
        return output
