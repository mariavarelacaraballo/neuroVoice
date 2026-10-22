"""POST /expand: iniciales/pictos → 5 frases. Es la ruta que mide el benchmark. [Pedro]"""
import time

from fastapi import APIRouter

from .. import config
from ..models import ExpandIn

router = APIRouter()


@router.post("/expand")
def expand(body: ExpandIn):
    if config.MOCK:
        return {"candidates": ["My back hurts", "My back hurts, call the nurse", "My back hurts again", "My back hurts since yesterday", "My back hurts a lot"],
                "suggested_tone": "molesto", "trace": [], "latency_ms": 0, "cost_eur": 0.0}
    from ..agent.agent import expand as agent_expand
    from ..db import clickhouse, postgres, valkey

    t0 = time.perf_counter()
    given = body.context.model_dump(exclude_none=True) if body.context else {}
    if body.memories is not None:
        # Modo benchmark: aislado. Solo el contexto y la memoria que manda el benchmark (ablación limpia).
        context, state = {k: v for k, v in given.items() if k != "state"}, ({"activation": given["state"]} if "state" in given else {})
    else:
        context = {**valkey.get_session(body.user_id), **given}
        context.setdefault("time", time.strftime("%H:%M"))
        if given.get("last_utterance"):
            valkey.add_turn(body.user_id, context.get("interlocutor") or "otra persona", given["last_utterance"])
        context["conversation"] = valkey.get_history(body.user_id)
        state = valkey.get_state(body.user_id)

    h = valkey.key_hash(body.user_id, body.mode, body.input, context.get("interlocutor"), context.get("last_utterance"),
                         str(context.get("conversation", [])[-4:]))
    if body.memories is None:
        hit = valkey.cache_get("expand", h)
        if hit:
            return {**hit, "latency_ms": int((time.perf_counter() - t0) * 1000), "cached": True}
    try:
        profile = postgres.profile_text(postgres.get_profile(body.user_id))
    except Exception:
        profile = "Lucas, 58 años, ELA"
    out = agent_expand(body.user_id, body.mode, body.input, context, state,
                       profile=profile,
                       fixed_memories=body.memories,
                       log=None if body.memories is not None else
                       (lambda step, tool, args, summary, ms: postgres.log_step(body.user_id, "", step, tool, args, summary, ms)))
    fallback = any("respaldo" in (t.get("result_summary") or "") for t in out.get("trace", []))
    if body.memories is None and out["candidates"] and not fallback:
        valkey.cache_set("expand", h, out, ttl=3600)
    try:
        clickhouse.log_metric(body.user_id, "expand", out["latency_ms"], out["cost_eur"], 0)
    except Exception:
        pass
    return out
