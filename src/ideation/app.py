"""The Ideation Engine's founder-facing Lambda (ADR-0018 §1).

A FastAPI + Mangum app, reached by a logged-in founder at ``<base>/ideation/api/*``
on the shared CloudFront. It authenticates every request itself — the SDK's
``require_group("founder")`` verifies the shared-Cognito JWT and requires the
``founder`` group — then drives :class:`~ideation.service.IdeationService` over the
HTTP ``CoreGateway``, forwarding the founder's token so Core owns identity and
owner-scoping (ADR-0017 §3/§5). It holds **no data** (ADR-0002).

``handler`` (bottom) is the Lambda entrypoint the manifest's ``user_ingress``
declares (``ideation.app.handler``).
"""

from __future__ import annotations

import os

from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from mangum import Mangum
from pydantic import BaseModel, Field

from .adapter import CoreHttpGateway
from .definitions import MAX_TURNS, MIN_TURNS
from .models import ANALYSING, GATHERING
from .service import (
    AnalysisFailed,
    IdeationError,
    IdeationService,
    MalformedReport,
    NotEnoughTurns,
    NotGathering,
    SessionNotFound,
    TurnLimitReached,
)
from .transport import CoreTransport

_CHAT_MODEL = os.environ.get("IDEATION_CHAT_MODEL", "anthropic/claude-sonnet-4")
_ANALYSIS_MODEL = os.environ.get("IDEATION_ANALYSIS_MODEL", "anthropic/claude-opus-4-8")

#: The founder gate — verifies the shared-Cognito JWT and requires the group. The
#: verified user carries its raw token, forwarded to Core by the transport.
require_founder = require_group("founder")


def get_service(founder: ForwardedUser = Depends(require_founder)) -> IdeationService:
    """One :class:`IdeationService` per request, bound to Core over a transport that
    signs as this Lambda AND forwards *this* founder's token."""
    transport = CoreTransport(founder_token=founder.token)
    return IdeationService(
        CoreHttpGateway(transport),
        chat_model=_CHAT_MODEL,
        analysis_model=_ANALYSIS_MODEL,
    )


app = FastAPI(title="Ideation Engine", docs_url=None, redoc_url=None)

# Orchestration errors → HTTP. Registered once for the base class; the map keys on
# the concrete type. Anything unmapped is a 400 (a bad request the founder can fix).
_ERROR_STATUS: dict[type[IdeationError], int] = {
    SessionNotFound: 404,
    NotGathering: 409,
    TurnLimitReached: 409,
    NotEnoughTurns: 422,
    AnalysisFailed: 502,
    MalformedReport: 502,
}


@app.exception_handler(IdeationError)
async def _on_ideation_error(_: Request, exc: IdeationError) -> JSONResponse:
    status = _ERROR_STATUS.get(type(exc), 400)
    return JSONResponse(
        status_code=status, content={"detail": str(exc) or type(exc).__name__}
    )


class StartSessionRequest(BaseModel):
    seed_idea: str = Field(min_length=1, max_length=16_000)


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)


def _state(session) -> dict:  # type: ignore[no-untyped-def]
    return {
        "session_id": session.id,
        "status": session.status,
        "turn_count": session.turn_count,
        "min_turns": MIN_TURNS,
        "max_turns": MAX_TURNS,
        "can_finalise": session.status == GATHERING and session.turn_count >= MIN_TURNS,
    }


@app.post("/sessions", status_code=201)
async def start_session(
    body: StartSessionRequest,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """Open a session for the founder's idea and run the first challenger turn (the
    idea is turn 1's fenced message). Returns the challenger's opening reply."""
    session = await svc.start_session(owner_sub=founder.sub, seed_idea=body.seed_idea)
    turn = await svc.chat_turn(
        owner_sub=founder.sub, session_id=session.id, user_message=body.seed_idea
    )
    state = await svc.get_session(owner_sub=founder.sub, session_id=session.id)
    return {"reply": turn.reply, **_state(state)}


@app.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: MessageRequest,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """One founder turn in the requirement-gathering chat."""
    turn = await svc.chat_turn(
        owner_sub=founder.sub, session_id=session_id, user_message=body.message
    )
    state = await svc.get_session(owner_sub=founder.sub, session_id=session_id)
    return {"reply": turn.reply, **_state(state)}


@app.get("/sessions/{session_id}")
async def read_session(
    session_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """The session's current state — for the UI to know whether to keep chatting,
    offer *finalise*, or poll for the report."""
    return _state(await svc.get_session(owner_sub=founder.sub, session_id=session_id))


@app.post("/sessions/{session_id}/finalise", status_code=202)
async def finalise(
    session_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """Kick the async analysis run; poll ``GET .../report`` for the result."""
    run_id = await svc.finalise(owner_sub=founder.sub, session_id=session_id)
    return {"status": ANALYSING, "analysis_run_id": run_id}


@app.get("/sessions/{session_id}/report")
async def read_report(
    session_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """The PRD + scorecard once ready. ``report`` is ``null`` while still gathering
    or analysing; the completed analysis is materialised on this poll (ADR-0017 §5
    trust model)."""
    report = await svc.get_report(owner_sub=founder.sub, session_id=session_id)
    state = await svc.get_session(owner_sub=founder.sub, session_id=session_id)
    return {"status": state.status, "report": report}


handler = Mangum(app)
