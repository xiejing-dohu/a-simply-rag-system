from pydantic import BaseModel
from typing import List

class ModelInfo(BaseModel):
    id: str
    name: str
    description: str
    provider: str

class ModelListResponse(BaseModel):
    models: List[ModelInfo]
