from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str = Field(..., min_length=1, max_length=50000)

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        # Bersihkan karakter null byte atau whitespace ekstrem
        cleaned = v.replace("\x00", "").strip()
        if not cleaned:
            raise ValueError("Pesan tidak boleh kosong.")
        return cleaned


class AIRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=-1, le=32768)


class AIResponse(BaseModel):
    content: str
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
