"""POST /listen: audio del navegador → texto (se guarda solo el texto). [Pedro]"""
from fastapi import APIRouter, File, Form, UploadFile

from .. import config

router = APIRouter()


@router.post("/listen")
async def listen(audio: UploadFile = File(...), user_id: str = Form("lucas")):
    if config.MOCK:
        return {"text": "Hi Dad! How was your day?"}
    from ..db import valkey
    from ..services.transcribe import transcribe
    data = await audio.read()
    try:
        text = transcribe(data, audio.filename or "audio.webm")
    except Exception as e:  # audio raro: no rompemos la app, devolvemos texto vacío
        return {"text": "", "error": f"transcription failed ({len(data)} bytes, {audio.content_type}): {str(e)[:150]}"}
    if not text:
        return {"text": "", "error": "empty or too short audio, please repeat"}
    valkey.set_session(user_id, last_utterance=text)
    valkey.add_turn(user_id, valkey.get_session(user_id).get("interlocutor") or "otra persona", text)
    return {"text": text}
