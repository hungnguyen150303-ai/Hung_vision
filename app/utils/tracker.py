import time, numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Tuple

@dataclass
class Track:
    id: int
    bbox: Tuple[int, int, int, int]
    last_seen: float
    history: deque
    side: str
    counted_in: bool
    counted_out: bool

class CentroidTracker:
    def __init__(self, max_distance: float = 80.0, max_age: float = 1.2):
        self.next_id = 1
        self.tracks: Dict[int, Track] = {}
        self.max_distance = max_distance
        self.max_age = max_age

    @staticmethod
    def _centroid(b):
        x1, y1, x2, y2 = b
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    def update(self, detections: List[Tuple[int,int,int,int]]):
        now = time.time()
        det_centroids = [self._centroid(b) for b in detections]
        unmatched = set(range(len(detections)))

        for tid in sorted(self.tracks.keys(), key=lambda i: -self.tracks[i].last_seen):
            tr = self.tracks[tid]
            tcx, tcy = self._centroid(tr.bbox)
            best_j, best_dist = -1, 1e9
            for j in list(unmatched):
                dcx, dcy = det_centroids[j]
                dist = np.hypot(tcx-dcx, tcy-dcy)
                if dist < best_dist:
                    best_dist, best_j = dist, j
            if best_j != -1 and best_dist <= self.max_distance:
                tr.bbox = detections[best_j]
                tr.last_seen = now
                tr.history.append(self._centroid(tr.bbox))
                if len(tr.history) > 20: tr.history.popleft()
                unmatched.remove(best_j)

        for j in unmatched:
            b = detections[j]
            tr = Track(
                id=self.next_id, bbox=b, last_seen=now,
                history=deque([self._centroid(b)], maxlen=20),
                side='unknown', counted_in=False, counted_out=False,
            )
            self.tracks[self.next_id] = tr
            self.next_id += 1

        to_del = [tid for tid, tr in self.tracks.items() if now - tr.last_seen > self.max_age]
        for tid in to_del: del self.tracks[tid]
        return self.tracks

def get_side(x_cen: int, line_x: int) -> str:
    return 'left' if x_cen < line_x else 'right'

def is_inside(side: str, camera_side: str) -> bool:
    return side == ('right' if camera_side == 'left' else 'left')
