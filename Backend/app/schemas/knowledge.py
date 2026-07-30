from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class KBCreate(BaseModel):
    name: str
    description: Optional[str] = None

class KBResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    collection_name: str
    file_count: int
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True
