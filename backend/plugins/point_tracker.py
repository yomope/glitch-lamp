import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class PointTrackerEffect(VideoEffect):
    def __init__(self):
        self.num_points = 10
        self.point_color = "#00FF00"
        self.text_color = "#FFFFFF"
        self.spline_color = "#0000FF"
        self.spline_type = "bezier"
        self.show_bbox = True
        
        self.tracks = []
        self.prev_gray = None
        self.next_id = 0

    @property
    def name(self):
        return "point_tracker"

    @property
    def description(self):
        return "Track points and connect them with a spline"

    @property
    def options(self):
        return [
            {"name": "num_points", "type": "int", "default": 10, "min": 1, "max": 50, "label": "Number of Points", "tooltip": "How many feature points to track."},
            {"name": "point_color", "type": "text", "default": "#00FF00", "label": "Point Color (Hex)", "tooltip": "Color of the tracked dots."},
            {"name": "text_color", "type": "text", "default": "#FFFFFF", "label": "Text Color (Hex)", "tooltip": "Color of the point labels."},
            {"name": "spline_color", "type": "text", "default": "#0000FF", "label": "Spline Color (Hex)", "tooltip": "Color of the curve connecting points."},
            {"name": "spline_type", "type": "select", "default": "bezier", "options": ["bezier", "polyline"], "label": "Spline Type", "tooltip": "Smooth curve (bezier) or straight segments (polyline)."},
            {"name": "show_bbox", "type": "bool", "default": True, "label": "Show Bounding Box", "tooltip": "Draw a box around all tracked points."}
        ]

    def update_options(self, options: dict):
        self.num_points = int(options.get("num_points", self.num_points))
        self.point_color = options.get("point_color", self.point_color)
        self.text_color = options.get("text_color", self.text_color)
        self.spline_color = options.get("spline_color", self.spline_color)
        self.spline_type = options.get("spline_type", self.spline_type)
        self.show_bbox = options.get("show_bbox", self.show_bbox)

    def _hex_to_bgr(self, hex_color):
        hex_color = str(hex_color).lstrip('#')
        if len(hex_color) != 6:
            return (0, 255, 0)
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (b, g, r)
        except ValueError:
            return (0, 255, 0)

    def _catmull_rom_spline(self, P0, P1, P2, P3, n_points=20):
        t = np.linspace(0, 1, n_points)
        t2 = t * t
        t3 = t2 * t
        
        M = 0.5 * np.array([
            [ 0,  2,  0,  0],
            [-1,  0,  1,  0],
            [ 2, -5,  4, -1],
            [-1,  3, -3,  1]
        ])
        
        P = np.array([P0, P1, P2, P3])
        
        points = []
        for val in t:
            T = np.array([1, val, val**2, val**3])
            pt = T @ M @ P
            points.append(pt)
            
        return np.array(points)

    def _get_spline_points(self, points):
        if len(points) < 2:
            return np.array(points, dtype=np.int32)
            
        P = np.array(points)
        # Pad with first and last points for Catmull-Rom
        P = np.vstack((P[0], P, P[-1]))
        
        curve_points = []
        for i in range(len(P) - 3):
            new_pts = self._catmull_rom_spline(P[i], P[i+1], P[i+2], P[i+3])
            curve_points.append(new_pts)
            
        return np.vstack(curve_points).astype(np.int32)

    def reset(self):
        self.tracks = []
        self.prev_gray = None
        self.next_id = 0

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Check if dimensions match
        if self.prev_gray is not None:
            if self.prev_gray.shape != frame_gray.shape:
                # Dimensions changed, reset tracking
                self.prev_gray = None
                self.tracks = []

        if self.prev_gray is None:
            self.prev_gray = frame_gray
            p0 = cv2.goodFeaturesToTrack(frame_gray, mask=None, maxCorners=self.num_points, qualityLevel=0.3, minDistance=7, blockSize=7)
            if p0 is not None:
                for x, y in p0.reshape(-1, 2):
                    self.tracks.append({'id': self.next_id, 'pt': (x, y)})
                    self.next_id += 1
            return frame

        if len(self.tracks) > 0:
            p0 = np.float32([t['pt'] for t in self.tracks]).reshape(-1, 1, 2)
            p1, st, err = cv2.calcOpticalFlowPyrLK(self.prev_gray, frame_gray, p0, None, winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
            
            good_new = []
            if p1 is not None:
                for i, (new, status) in enumerate(zip(p1, st)):
                    if status == 1:
                        self.tracks[i]['pt'] = (new[0][0], new[0][1])
                        good_new.append(self.tracks[i])
            self.tracks = good_new

        if len(self.tracks) < self.num_points:
            mask = np.ones_like(frame_gray)
            for t in self.tracks:
                cv2.circle(mask, (int(t['pt'][0]), int(t['pt'][1])), 10, 0, -1)
            
            p_new = cv2.goodFeaturesToTrack(frame_gray, mask=mask, maxCorners=self.num_points - len(self.tracks), qualityLevel=0.3, minDistance=7, blockSize=7)
            if p_new is not None:
                for x, y in p_new.reshape(-1, 2):
                    self.tracks.append({'id': self.next_id, 'pt': (x, y)})
                    self.next_id += 1

        self.prev_gray = frame_gray.copy()

        point_color = self._hex_to_bgr(self.point_color)
        text_color = self._hex_to_bgr(self.text_color)
        spline_color = self._hex_to_bgr(self.spline_color)

        points_coords = []
        for t in self.tracks:
            x, y = int(t['pt'][0]), int(t['pt'][1])
            points_coords.append((x, y))
            
            cv2.circle(frame, (x, y), 5, point_color, -1)
            
            label = f"ID:{t['id']} ({x},{y})"
            cv2.putText(frame, label, (x + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)

        if len(points_coords) >= 2:
            if self.spline_type == "bezier":
                curve_points = self._get_spline_points(points_coords)
                cv2.polylines(frame, [curve_points], False, spline_color, 2)
            else:
                cv2.polylines(frame, [np.array(points_coords, dtype=np.int32)], False, spline_color, 2)

        if self.show_bbox and len(points_coords) > 0:
            x_coords = [p[0] for p in points_coords]
            y_coords = [p[1] for p in points_coords]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            cv2.rectangle(frame, (min_x, min_y), (max_x, max_y), (0, 255, 255), 1)

        return frame
