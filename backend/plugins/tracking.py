import cv2
import numpy as np
from pathlib import Path
from urllib.request import urlretrieve
from backend.plugins.base import VideoEffect

class TrackingEffect(VideoEffect):
    MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    )

    def __init__(self):
        self.draw_tesselation = True
        self.line_thickness = 2
        self.line_color = (0, 255, 0)  # BGR
        self.overlay_image_path = None
        self.overlay_size = 12
        self._overlay_img = None
        self.available = False
        self._mode = None  # "solutions" or "tasks"
        self._processor = None
        self._tesselation = None
        self._timestamp_ms = 0.0
        self._frame_step_ms = 33.0
        self._mp = None

        try:
            import mediapipe as mp
            # self._mp = mp # Do not store module in self to avoid pickling errors
            if hasattr(mp, "solutions") and mp.solutions:
                # self._init_solutions(mp) # Deferred
                self._mode = "solutions"
                self.available = True
            elif hasattr(mp, "tasks") and hasattr(mp.tasks, "vision"):
                # self._init_tasks(mp) # Deferred
                self._mode = "tasks"
                self.available = True
            else:
                print("MediaPipe solutions/tasks not available, TrackingEffect disabled")
        except Exception as e:
            print(f"MediaPipe not available, TrackingEffect disabled: {e}")

    def _lazy_init(self):
        if not self.available:
            return

        import mediapipe as mp # Import locally

        if self._mode == "solutions" and not hasattr(self, "face_mesh"):
            self._init_solutions(mp)
        elif self._mode == "tasks" and self._processor is None:
            self._init_tasks(mp)

    @property
    def name(self):
        return "tracking"

    @property
    def description(self):
        return "Face mesh tracking visualization"

    @property
    def options(self):
        return [
            {"name": "draw_tesselation", "type": "bool", "default": True, "label": "Dessiner la tesselation", "tooltip": "Superpose le maillage du visage."},
            {"name": "line_thickness", "type": "int", "default": 2, "min": 1, "max": 10, "label": "Épaisseur des traits"},
            {"name": "line_color", "type": "text", "default": "#00ff00", "label": "Couleur (hex)", "tooltip": "Ex: #00ff00"},
            {"name": "overlay_image_path", "type": "text", "default": "", "label": "Image JPEG à tamponner", "tooltip": "Chemin vers un .jpg/.jpeg (local)."},
            {"name": "overlay_size", "type": "int", "default": 12, "min": 4, "max": 64, "label": "Taille du tampon (px)"}
        ]

    def update_options(self, options: dict):
        self.draw_tesselation = options.get("draw_tesselation", self.draw_tesselation)
        self.line_thickness = int(max(1, min(10, options.get("line_thickness", self.line_thickness))))
        self.line_color = self._parse_color(options.get("line_color", "#00ff00"))
        self.overlay_size = int(max(4, min(64, options.get("overlay_size", self.overlay_size))))

        path = options.get("overlay_image_path") or ""
        path = path.strip()
        self.overlay_image_path = path if path else None
        self._overlay_img = self._load_overlay(self.overlay_image_path, self.overlay_size)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        if not self.available:
            return frame

        self._lazy_init()

        fps = kwargs.get("fps")
        frame_index = kwargs.get("frame_index", 0)

        if frame_index == 0:
            print(f"Tracking active (mode={self._mode}, draw_tesselation={self.draw_tesselation})")

        if self._mode == "solutions":
            return self._apply_solutions(frame, frame_index)
        if self._mode == "tasks":
            return self._apply_tasks(frame, fps=fps, frame_index=frame_index)
        return frame

    def reset(self):
        self._timestamp_ms = 0.0

    def _ensure_model(self) -> str:
        """Download the face landmarker model if missing and return its path."""
        backend_dir = Path(__file__).resolve().parents[1]
        model_dir = backend_dir / "models"
        model_dir.mkdir(exist_ok=True)
        model_path = model_dir / "face_landmarker.task"

        if not model_path.exists():
            try:
                print("Downloading MediaPipe face_landmarker.task (~13MB)...")
                urlretrieve(self.MODEL_URL, model_path)
            except Exception as exc:
                raise RuntimeError(f"Unable to download MediaPipe model: {exc}")

        return str(model_path)

    def _init_solutions(self, mp):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        self._mode = "solutions"
        self.available = True

    def _init_tasks(self, mp):
        vision = mp.tasks.vision

        try:
            model_path = self._ensure_model()
            options = vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                num_faces=1,
            )
            self._processor = vision.FaceLandmarker.create_from_options(options)
            self._tesselation = vision.FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION
            self._mode = "tasks"
            self.available = True
        except Exception as exc:
            print(f"MediaPipe tasks setup failed, TrackingEffect disabled: {exc}")
            self.available = False

    def _apply_solutions(self, frame: np.ndarray, frame_index: int) -> np.ndarray:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_frame)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                if self.draw_tesselation:
                    spec = self.mp_drawing.DrawingSpec(thickness=self.line_thickness, circle_radius=1, color=self.line_color)
                    self.mp_drawing.draw_landmarks(
                        image=frame,
                        landmark_list=face_landmarks,
                        connections=self.mp_face_mesh.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=spec,
                    )
                    self._maybe_stamp_overlay(frame, face_landmarks.landmark)
                    if frame_index % 30 == 0:
                        print("Tracking: face mesh drawn (solutions)")
        elif frame_index % 30 == 0:
            print("Tracking: no face detected (solutions)")
        return frame

    def _apply_tasks(self, frame: np.ndarray, fps: float | None = None, frame_index: int = 0) -> np.ndarray:
        if not self._processor:
            return frame

        import mediapipe as mp # Import locally

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        try:
            result = self._processor.detect(mp_image)
        except Exception as exc:
            if frame_index % 30 == 0:
                print(f"Tracking: detect error: {exc}")
            return frame

        if not result or not result.face_landmarks or not self.draw_tesselation:
            if frame_index % 30 == 0:
                print("Tracking: no face detected (tasks)")
            return frame

        height, width, _ = frame.shape
        color = self.line_color
        thickness = self.line_thickness

        for landmarks in result.face_landmarks:
            points = [
                (int(min(max(lm.x, 0.0), 1.0) * width), int(min(max(lm.y, 0.0), 1.0) * height))
                for lm in landmarks
            ]

            for connection in self._tesselation or []:
                start = points[connection.start]
                end = points[connection.end]
                cv2.line(frame, start, end, color, thickness, cv2.LINE_AA)

            self._maybe_stamp_overlay(frame, landmarks)

            if frame_index % 30 == 0:
                print("Tracking: face mesh drawn (tasks)")

        return frame

    def _parse_color(self, value: str) -> tuple:
        try:
            v = value.lstrip('#')
            if len(v) == 6:
                r = int(v[0:2], 16)
                g = int(v[2:4], 16)
                b = int(v[4:6], 16)
                return (b, g, r)  # BGR
        except Exception:
            pass
        return (0, 255, 0)

    def _load_overlay(self, path: str | None, size: int):
        if not path:
            return None
        p = Path(path)
        if not p.exists() or p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            print(f"Tracking: overlay not found or unsupported: {path}")
            return None
        try:
            img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if img is None:
                print(f"Tracking: unable to read overlay image: {path}")
                return None
            resized = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
            return resized
        except Exception as exc:
            print(f"Tracking: failed to load overlay: {exc}")
            return None

    def _maybe_stamp_overlay(self, frame: np.ndarray, landmarks):
        if self._overlay_img is None:
            return

        h, w, _ = frame.shape
        overlay = self._overlay_img
        oh, ow = overlay.shape[:2]

        for idx, lm in enumerate(landmarks):
            # Stamp every 5th landmark to reduce cost
            if idx % 5 != 0:
                continue

            x = int(min(max(lm.x, 0.0), 1.0) * w)
            y = int(min(max(lm.y, 0.0), 1.0) * h)

            x0 = max(0, x - ow // 2)
            y0 = max(0, y - oh // 2)
            x1 = min(w, x0 + ow)
            y1 = min(h, y0 + oh)

            roi = frame[y0:y1, x0:x1]
            oh2, ow2 = roi.shape[:2]
            if oh2 == 0 or ow2 == 0:
                continue

            overlay_resized = overlay
            if (oh2, ow2) != (oh, ow):
                overlay_resized = cv2.resize(overlay, (ow2, oh2), interpolation=cv2.INTER_AREA)

            if overlay_resized.shape[2] == 4:
                alpha = overlay_resized[:, :, 3] / 255.0
                for c in range(3):
                    roi[:, :, c] = (1 - alpha) * roi[:, :, c] + alpha * overlay_resized[:, :, c]
            else:
                roi[:] = overlay_resized

            frame[y0:y1, x0:x1] = roi
