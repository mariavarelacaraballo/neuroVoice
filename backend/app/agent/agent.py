"""Bucle del agente (Claude con tool use). [Pedro]

expand() es LA función que usan la app (/expand) y el benchmark (vía EXPAND_URL).
"""
import json
import re
import time
import uuid

import anthropic

from .. import config
from .prompts import SYSTEM
from .tools import TOOLS, run_tool

MAX_ROUNDS = 3
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def create(**kw):
    """Llamada sin 'thinking' (si el modelo lo usa por defecto, se come los tokens y no llega a responder).
    Si la API no acepta desactivarlo, reintenta con más tokens."""
    try:
        return client().messages.create(max_tokens=1000, thinking={"type": "disabled"}, **kw)
    except anthropic.BadRequestError:
        return client().messages.create(max_tokens=8000, **kw)


def expand(user_id: str, mode: str, user_input, context: dict, state: dict, profile: str = "",
           fixed_memories: list[str] | None = None, log=None) -> dict:
    """Devuelve {candidates, suggested_tone, trace, latency_ms, cost_eur}.

    log: función (step, tool, args, summary, ms) para escribir en agent_log (None en benchmark).
    """
    t0 = time.perf_counter()
    request_id = uuid.uuid4().hex[:8]
    ctx = {"user_id": user_id, "context": context, "state": state, "fixed_memories": fixed_memories}
    shown = user_input if isinstance(user_input, str) else " + ".join(user_input)
    trace, cost = [], 0.0

    # Prefetch (rápido): las 3 consultas de datos que el agente siempre necesita, sin esperar a Claude.
    prefetched = []
    initials = shown if mode == "initials" else ""
    for step, (tool, args) in enumerate([("search_memory", {"initials": initials, "interlocutor": (context or {}).get("interlocutor")}),
                                         ("get_context", {}), ("get_state", {})]):
        t1 = time.perf_counter()
        result = run_tool(tool, args, ctx)
        ms = int((time.perf_counter() - t1) * 1000)
        trace.append({"tool": tool, "args": args, "result_summary": result[:120], "ms": ms})
        if log:
            log(step, tool, args, result[:120], ms)
        prefetched.append(f"[{tool}] {result}")
    messages = [{"role": "user", "content": f"Mode: {mode}. User input (initials): {shown}\n\n"
                 "Data already fetched for you (do not repeat these tools):\n"
                 + "\n".join(prefetched)
                 + "\n\nIf it is about current events use web_search; otherwise answer directly."}]
    system = SYSTEM.format(name=profile.split()[0] if profile else "el usuario", profile=profile)
    def matches(phrase):
        words = re.findall(r"[\wáéíóúñü']+", phrase.lower())
        want = initials.split()
        return len(words) >= len(want) and all(w.startswith(i) for w, i in zip(words, want))

    def final(out, why=""):
        cands = list(dict.fromkeys(str(c) for c in out.get("candidates", [])))
        # No repetir lo que Lucas ya acaba de decir en esta conversación
        said = {t.get("text", "").strip().lower() for t in (context or {}).get("conversation", []) if t.get("who") == "Lucas"}
        cands = [c for c in cands if c.strip().lower() not in said] or cands
        if initials:
            good = [c for c in cands if matches(c)]
            cands = good or cands  # si ninguna encaja, mejor algo que nada
        return {
            "candidates": cands[:5],
            "suggested_tone": out.get("suggested_tone", "neutro"),
            "trace": trace + [{"tool": "propose_phrases", "args": {}, "result_summary": out.get("why", why), "ms": 0}],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "cost_eur": round(cost * 0.92, 5),  # USD→EUR aproximado
            "request_id": request_id,
        }

    # Respuesta en JSON: más fiable y rápido que forzar la herramienta final (este modelo no admite tool_choice).
    messages[0]["content"] += ("\n\nReply ONLY with a JSON object, no text around it, sentences in ENGLISH: "
                               '{"candidates": [5 sentences], "suggested_tone": "neutro|tranquilo|contento|cansado|molesto|urgente", '
                               '"why": "one line"}')
    web_tools = [t for t in TOOLS if t["name"] == "web_search"] if config.KEENABLE_API_KEY else []

    prev_good = []
    for step in range(MAX_ROUNDS):
        kwargs = {"tools": web_tools} if web_tools else {}
        msg = create(model=config.EXPAND_MODEL, system=system, messages=messages, **kwargs)
        cost += msg.usage.input_tokens / 1e6 * config.PRICE_IN + msg.usage.output_tokens / 1e6 * config.PRICE_OUT
        messages.append({"role": "assistant", "content": msg.content})
        results = []
        for block in msg.content:
            if block.type == "tool_use":
                t1 = time.perf_counter()
                result = run_tool(block.name, block.input, ctx)
                ms = int((time.perf_counter() - t1) * 1000)
                trace.append({"tool": block.name, "args": block.input, "result_summary": result[:120], "ms": ms})
                if log:
                    log(3 + step, block.name, block.input, result[:120], ms)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        if results:
            messages.append({"role": "user", "content": results})
            continue
        text = " ".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            out = json.loads(m.group(0)) if m else {}
        except Exception:
            out = {}
        if not out.get("candidates"):
            m2 = re.search(r"\[.*\]", text, re.S)
            try:
                out = {"candidates": json.loads(m2.group(0))} if m2 else {}
            except Exception:
                out = {}
        if out.get("candidates"):
            good = [c for c in out["candidates"] if not initials or matches(str(c))]
            if len(good) < 5 and step < MAX_ROUNDS - 1:
                bad = [c for c in out["candidates"] if c not in good]
                messages.append({"role": "user", "content":
                    f"These do NOT fit the initials '{initials}' (each word, in order, no extra words at the start): {bad}. "
                    f"Valid: {good}. Return the JSON with 5 varied English sentences that DO fit."})
                prev_good = list(dict.fromkeys(prev_good + good))
                continue
            out["candidates"] = list(dict.fromkeys(good + prev_good))
            return final(out)
        raw_debug = f"stop={msg.stop_reason} bloques={[b.type for b in msg.content]} texto={text[:160]!r}"
        break
    else:
        raw_debug = "sin respuesta final"

    # Respaldo: frases de la memoria con esas iniciales (nunca devolvemos la lista vacía si hay recuerdos).
    try:
        mem = json.loads(run_tool("search_memory", {"initials": initials}, ctx))
        cands = list(dict.fromkeys(m["phrase"] if isinstance(m, dict) else str(m) for m in mem))[:5]
    except Exception:
        cands = []
    return final({"candidates": cands, "suggested_tone": "neutro"}, why="fallback from memory (respaldo) · " + raw_debug)

    return {"candidates": [], "suggested_tone": "neutro", "trace": trace,
            "latency_ms": int((time.perf_counter() - t0) * 1000), "cost_eur": round(cost * 0.92, 5)}


# TODO(Pedro), optimización si la latencia pasa de ~3 s:
#  - Prefetch en /context: search_memory del interlocutor y guardarlo en ctx para ahorrar una ronda.
#  - Caché en Valkey por (user, input, interlocutor).
#  - Probar un modelo más rápido para /expand y dejar el grande para /context.
