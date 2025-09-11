from ultralytics import YOLO

class YoloModel:
    def __init__(self, model_path: str, device: str = "auto", conf: float = 0.35):
        self.model_path = model_path
        self.conf = conf
        if device == "auto":
            try:
                import torch
                self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except Exception:
                self.device = "cpu"
        else:
            self.device = device
        self.model = YOLO(self.model_path)

    def detect_person(self, frame):
        return self.model(frame, conf=self.conf, device=self.device, verbose=False, classes=[0])[0]
