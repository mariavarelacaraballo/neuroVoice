"""ElevenLabs: voz clonada con tono. [Marc + Pedro]

Mapeo tono → audio tag de eleven_v3 (los tags van en inglés aunque el texto sea en español o francés).
TODO(Marc, 12:30): probar cada tag con la voz clonada en ES y FR y ajustar esta tabla con lo que suene mejor.
"""
import time

from elevenlabs.client import ElevenLabs

from .. import config
from ..db import valkey

TONE_TAGS = {
    "neutro": "",
    "tranquilo": "[calm]",
    "contento": "[cheerful]",
    "cansado": "[tired]",
    "molesto": "[annoyed]",
    "urgente": "[urgent]",
    "neutral": "", "calm": "[calm]", "happy": "[cheerful]", "tired": "[tired]", "annoyed": "[annoyed]", "urgent": "[urgent]",
}

_el = None


def el():
    global _el
    if _el is None:
        _el = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    return _el


def translate(text: str, language: str) -> str:
    """Traduce la frase elegida manteniendo el registro (primera persona, natural)."""
    import anthropic
    names = {"fr": "francés", "en": "inglés"}
    msg = anthropic.Anthropic().messages.create(
        model=config.AGENT_MODEL, max_tokens=200,
        messages=[{"role": "user", "content": f"Traduce al {names.get(language, language)} esta frase, natural y en primera persona. "
                                              f"Responde solo con la traducción.\n\n{text}"}])
    return msg.content[0].text.strip()


def speak(user_id: str, text: str, tone: str, language: str) -> dict:
    """Devuelve {audio_url | audio_b64, cached, latency_ms}.
    TODO(Pedro): subir el MP3 a Supabase Storage (services/storage.py) y devolver la URL; si no hay Supabase, base64.
    """
    t0 = time.perf_counter()
    h = valkey.key_hash(user_id, text, tone, language)
    hit = valkey.cache_get("audio", h)
    if hit:
        return {**hit, "cached": True, "latency_ms": int((time.perf_counter() - t0) * 1000)}
    # Las frases ya vienen en el idioma que se habla (inglés): no se traduce.
    try:
        audio = b"".join(el().text_to_speech.convert(
            voice_id=config.VOICE_ID, text=f"{TONE_TAGS.get(tone, '')} {text}".strip(),
            model_id=config.TTS_MODEL, output_format="mp3_44100_128"))
    except Exception as e:
        # Respaldo: modelo multilingüe v2 sin etiquetas de tono (las leería en voz alta)
        print("ElevenLabs v3 falló, uso multilingual_v2:", getattr(e, "status_code", ""), getattr(e, "body", e))
        audio = b"".join(el().text_to_speech.convert(
            voice_id=config.VOICE_ID, text=text, model_id="eleven_multilingual_v2", output_format="mp3_44100_128"))
    from .storage import upload_audio
    out = upload_audio(h, audio)
    valkey.cache_set("audio", h, out, ttl=86400)
    return {**out, "cached": False, "latency_ms": int((time.perf_counter() - t0) * 1000)}
