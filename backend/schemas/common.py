from pydantic import BaseModel


class APIResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None
