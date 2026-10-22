"""POST /choice: el usuario eligió o editó → el agente aprende. [Pedro]"""
from fastapi import APIRouter

from .. import config
from ..models import ChoiceIn

router = APIRouter()


@router.post("/choice")
def choice(body: ChoiceIn):
    if config.MOCK:
        return {"ok": True, "learned": "(mock) saved to memory"}
    from ..agent.memory import learn_from_choice
    from ..db import valkey

    final = body.edited_text or body.chosen
    session = valkey.get_session(body.user_id)
    state = valkey.get_state(body.user_id)
    result = learn_from_choice(body.user_id, final, session.get("interlocutor"), state.get("activation"),
                               session.get("last_utterance"), edited=bool(body.edited_text))
    valkey.add_turn(body.user_id, "Lucas", final)
    try:
        from ..db import postgres
        postgres.save_choice(body.model_dump())
    except Exception:
        pass
    return {"ok": True, "learned": f"Sentence {'reinforced' if result == 'reforzada' else 'saved'} in memory"}
