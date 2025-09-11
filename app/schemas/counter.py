from pydantic import BaseModel

class StartRequest(BaseModel):
    camera_side: str | None = None
    line_x: float | None = None
    model: str | None = None
    conf: float | None = None
    device: str | None = None
    rs_width: int | None = None
    rs_height: int | None = None
    rs_fps: int | None = None
    use_depth: bool | None = None
    min_dist: float | None = None
    max_dist: float | None = None
    enter_window: float | None = None
    log_interval: float | None = None

class StatusResponse(BaseModel):
    running: bool
    total_in: int
    total_out: int
    tracks: int
    config: dict
