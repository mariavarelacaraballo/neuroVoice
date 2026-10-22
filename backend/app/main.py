"""API de NeuroVoice (FastAPI). Se despliega en Aiven Runtime. [Pedro]

Arranque local:  uvicorn backend.app.main:app --reload
Despliegue: TODO(Pedro) seguir la guía de Aiven Runtime (comando de arranque = el de arriba con --host 0.0.0.0 --port $PORT).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .routes import choice, context, expand, health, listen, speak, state, trace, wearable

app = FastAPI(title="NeuroVoice API")
app.add_middleware(CORSMiddleware, allow_origins=[config.FRONTEND_ORIGIN], allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(Exception)
async def show_error(request, exc):
    """Durante el hackathon: devolver el error completo para depurar rápido."""
    import traceback
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"error": repr(exc), "status": getattr(exc, "status_code", None), "body": str(getattr(exc, "body", ""))[:500], "trace": traceback.format_exc().splitlines()[-12:]})


for r in (health, context, expand, choice, speak, listen, wearable, state, trace):
    app.include_router(r.router)


# --- English everywhere: internal values are Spanish, the API speaks English ---
TONE_EN = {"neutro": "neutral", "tranquilo": "calm", "contento": "happy", "cansado": "tired",
           "molesto": "annoyed", "urgente": "urgent"}
TONE_ES = {v: k for k, v in TONE_EN.items()}
ACT_EN = {"alta": "high", "baja": "low", "media": "medium", "activación": "activation",
          "reposo": "rest", "estres": "stress", "diversion": "amusement"}
_TONE_KEYS = {"suggested_tone", "tone"}


def _to_en(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in _TONE_KEYS and isinstance(v, str):
                v = TONE_EN.get(v, v)
            elif k == "activation" and isinstance(v, str):
                v = ACT_EN.get(v, v)
            elif isinstance(v, str) and k == "result_summary":
                for a, b in {**TONE_EN, **ACT_EN}.items():
                    v = v.replace(f'"{a}"', f'"{b}"')
            else:
                v = _to_en(v)
            out[k] = v
        return out
    if isinstance(o, list):
        return [_to_en(x) for x in o]
    return o


@app.middleware("http")
async def english(request, call_next):
    import json as _j
    from fastapi.responses import Response as _R
    response = await call_next(request)
    if "application/json" not in (response.headers.get("content-type") or ""):
        return response
    raw = b"".join([c async for c in response.body_iterator])
    try:
        raw = _j.dumps(_to_en(_j.loads(raw)), ensure_ascii=False).encode()
    except Exception:
        pass
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return _R(content=raw, status_code=response.status_code, headers=headers, media_type="application/json")


# --- Depuración en vivo: qué entra y qué sale (últimas 50 llamadas, en Valkey) ---
import json as _json
import time as _time

from fastapi import Request
from fastapi.responses import Response


@app.middleware("http")
async def debug_log(request: Request, call_next):
    if request.method != "POST" or request.url.path not in ("/expand", "/context", "/speak", "/choice", "/listen"):
        return await call_next(request)
    body = await request.body()
    t0 = _time.perf_counter()
    response = await call_next(request)
    chunks = [c async for c in response.body_iterator]
    raw = b"".join(chunks)
    try:
        out = _json.loads(raw)
        out = {k: v for k, v in out.items() if k in ("candidates", "suggestions", "suggested_tone", "learned", "text", "error", "cached")}
    except Exception:
        out = {"raw": raw[:200].decode(errors="ignore")}
    try:
        inp = _json.loads(body) if request.url.path != "/listen" else {"audio": f"{len(body)} bytes"}
        inp.pop("candidates", None)
    except Exception:
        inp = {"raw": body[:200].decode(errors="ignore")}
    line = {"t": _time.strftime("%H:%M:%S"), "path": request.url.path, "ms": int((_time.perf_counter() - t0) * 1000),
            "in": inp, "out": out}
    print("DEBUG", _json.dumps(line, ensure_ascii=False), flush=True)
    try:
        from .db.valkey import r
        r().lpush("debug:log", _json.dumps(line, ensure_ascii=False))
        r().ltrim("debug:log", 0, 49)
    except Exception:
        pass
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(content=raw, status_code=response.status_code, headers=headers, media_type=response.media_type)


@app.get("/debug/log")
def debug_log_view(n: int = 10):
    from .db.valkey import r
    try:
        return [_json.loads(x) for x in r().lrange("debug:log", 0, n - 1)]
    except Exception as e:
        return {"error": repr(e)}
