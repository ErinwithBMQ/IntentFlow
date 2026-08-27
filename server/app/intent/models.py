from typing import Literal

from pydantic import BaseModel, Field

from app.agent.models import IntentBrief


class CanvasPosition(BaseModel):
    x: float
    y: float


class CanvasNote(BaseModel):
    id: str
    text: str
    label: Literal["idea", "behavior", "constraint", "acceptance"] | None = None
    position: CanvasPosition


class CanvasConnection(BaseModel):
    id: str
    source: str
    target: str
    label: str = ""


class IntentCanvas(BaseModel):
    notes: list[CanvasNote] = Field(default_factory=list)
    connections: list[CanvasConnection] = Field(default_factory=list)
    supplemental_text: str = ""


class CanvasCompileRequest(BaseModel):
    canvas: IntentCanvas


class CanvasCompileResponse(BaseModel):
    brief: IntentBrief
    compiler: Literal["local"] = "local"
    notice: str = "当前使用本地基线整理。"
