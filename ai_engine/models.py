from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant|tool)$")
    content: Optional[str] = Field(default=None, max_length=100000)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.replace("\x00", "")


class AIRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=-1, le=32768)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None


class AIResponse(BaseModel):
    content: str = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
