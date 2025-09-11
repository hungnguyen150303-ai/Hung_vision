from pydantic import BaseModel

class HealthResponse(BaseModel):
    live: bool = True
    ready: bool
