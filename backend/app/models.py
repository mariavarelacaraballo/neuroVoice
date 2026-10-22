"""Esquemas de entrada/salida. Deben coincidir con docs/api.md. [Pedro]"""
from typing import Literal

from pydantic import BaseModel

Tone = Literal["neutro", "tranquilo", "contento", "cansado", "molesto", "urgente",
               "neutral", "calm", "happy", "tired", "annoyed", "urgent"]  # acepta inglés y español


class Context(BaseModel):
    interlocutor: str | None = None
    last_utterance: str | None = None
    time: str | None = None        # "18:05"; si falta, hora actual
    state: str | None = None       # si falta, se lee de Valkey (wearable)


class ContextIn(BaseModel):
    user_id: str = "lucas"
    interlocutor: str | None = None
    last_utterance: str | None = None


class ExpandIn(BaseModel):
    user_id: str = "lucas"
    mode: Literal["initials", "pictos"] = "initials"
    input: str | list[str]
    context: Context | None = None
    memories: list[str] | None = None   # solo benchmark (ablación)


class TraceStep(BaseModel):
    tool: str
    args: dict
    result_summary: str
    ms: int


class ExpandOut(BaseModel):
    candidates: list[str]
    suggested_tone: Tone = "neutro"
    trace: list[TraceStep] = []
    latency_ms: int = 0
    cost_eur: float = 0.0


class ChoiceIn(BaseModel):
    user_id: str = "lucas"
    input: str | list[str]
    candidates: list[str]
    chosen: str
    edited_text: str | None = None
    tone: Tone = "neutro"
    tone_was_changed: bool = False


class SpeakIn(BaseModel):
    user_id: str = "lucas"
    text: str
    tone: Tone = "neutro"
    language: Literal["es", "fr", "en"] = "es"


class Sample(BaseModel):
    ts: str
    hr: float
    eda: float
    acc: float = 0.0


class SamplesIn(BaseModel):
    user_id: str = "lucas"
    samples: list[Sample]
