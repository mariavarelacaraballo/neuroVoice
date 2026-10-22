"""Herramientas del agente: definición (JSON schema para Claude) + implementación. [Pedro]

Cómo funciona el tool use de Claude:
- Pasamos TOOLS en messages.create(tools=TOOLS).
- Claude responde con bloques {"type": "tool_use", "name", "input", "id"}.
- Ejecutamos run_tool(name, input) y devolvemos {"type": "tool_result", "tool_use_id", "content"}.
- Repetimos hasta que llame a propose_phrases (herramienta final) o se agoten las rondas.
"""
import json

TOOLS = [
    {
        "name": "search_memory",
        "description": "Busca frases que el usuario ha dicho antes, con su contexto. Úsala siempre primero.",
        "input_schema": {
            "type": "object",
            "properties": {
                "initials": {"type": "string", "description": "Iniciales tal como las escribió, p. ej. 'm d l e'"},
                "query": {"type": "string", "description": "Texto libre para búsqueda semántica (tema, situación)"},
                "interlocutor": {"type": "string", "description": "Persona presente, si se conoce"},
                "k": {"type": "integer", "default": 8},
            },
            "required": [],
        },
    },
    {
        "name": "get_context",
        "description": "Devuelve quién está presente, lo último que le han dicho, la hora y las rutinas de esta franja.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_state",
        "description": "Estado estimado por la pulsera (activación, confianza) y tono sugerido para la voz.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "web_search",
        "description": "Busca información actual en la web (Keenable) cuando la frase trata de algo del mundo. Devuelve resultados con fuente.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "propose_phrases",
        "description": "Herramienta FINAL: entrega exactamente 5 frases candidatas ordenadas de más a menos probable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 5},
                "suggested_tone": {"type": "string",
                                   "enum": ["neutro", "tranquilo", "contento", "cansado", "molesto", "urgente"]},
                "why": {"type": "string", "description": "Una línea: en qué recuerdos o contexto te basas"},
            },
            "required": ["candidates", "suggested_tone"],
        },
    },
]


def run_tool(name: str, args: dict, ctx: dict) -> str:
    """Ejecuta una herramienta y devuelve texto (JSON) para el tool_result.

    ctx lleva: user_id, session (Valkey), state, fixed_memories (benchmark), etc.
    TODO(Pedro):
      search_memory → services: embed(query or initials) + db.postgres.search_memories(...)
                      si ctx["fixed_memories"] no es None (benchmark), devolver esas en su lugar.
      get_context   → db.valkey.get_session + rutinas de la hora (db.postgres.get_profile)
      get_state     → db.valkey.get_state
      web_search    → services.websearch.search(query)
    """
    if name == "search_memory":
        if ctx.get("fixed_memories") is not None:
            return json.dumps(ctx["fixed_memories"], ensure_ascii=False)
        from ..db import postgres
        from .memory import embed
        c = ctx.get("context") or {}
        q = args.get("query") or f"{args.get('interlocutor') or c.get('interlocutor', '')}: {c.get('last_utterance', '')}"
        # Con iniciales, la búsqueda exacta por iniciales basta (ahorra ~2 s de embedding); sin ellas, búsqueda semántica.
        emb = None if args.get("initials") else embed(q)
        rows = postgres.search_memories(ctx["user_id"], emb,
                                        initials=args.get("initials"), interlocutor=args.get("interlocutor"),
                                        k=args.get("k", 8))
        return json.dumps([{"phrase": r["phrase"], "interlocutor": r["interlocutor"], "times_used": r["times_used"]}
                           for r in rows], ensure_ascii=False)
    if name == "get_context":
        return json.dumps(ctx.get("context") or {}, ensure_ascii=False)
    if name == "get_state":
        return json.dumps(ctx.get("state") or {}, ensure_ascii=False)
    if name == "web_search":
        from ..services.websearch import search
        return json.dumps(search(args["query"]), ensure_ascii=False)
    return json.dumps({"error": f"unknown tool {name}"})
