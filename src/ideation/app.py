"""The Ideation Engine's founder-facing ASGI app (ADR-0021).

A FastAPI app mounted by the shared plugin host at ``/api/v1/plugins/ideation/*``.
The host authenticates the founder (its group gate verifies the shared-Cognito JWT
and requires the ``founder`` group) before dispatching here; this app *also* runs
``require_group("founder")`` per route — defence-in-depth, and the way it obtains
the founder's token to forward to Core over the HTTP ``CoreGateway`` so Core owns
identity and owner-scoping (ADR-0017 §3/§5). It holds **no data** (ADR-0002).

``app`` (the module-level FastAPI object) is what the manifest's ``user_ingress``
declares as ``ideation.app:app``; the host provides the Lambda entrypoint and
strips the ``/api/v1/plugins/ideation`` mount prefix, so the routes below stay
clean and the app is agnostic to where it is mounted. It no longer ships its own
Mangum handler.
"""

from __future__ import annotations

from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .adapter import CoreHttpGateway
from .definitions import MAX_TURNS, MIN_TURNS
from .effective_config import analysis_model
from .models import ANALYSING, GATHERING
from .service import (
    AnalysisFailedError,
    IdeationError,
    IdeationService,
    MalformedReportError,
    NotEnoughTurnsError,
    NotGatheringError,
    SessionNotFoundError,
    TurnLimitReachedError,
)
from .transport import CoreTransport

#: The analyst's fallback model, resolved by ``effective_config`` rather than
#: read from the environment here, so the admin panel's "what is actually in
#: use" view and this request path cannot disagree (issue #58).
#:
#: There is no chat equivalent. The challenger's model lives in its stored
#: chat-agent row and Core resolves it; a value held here was passed to the
#: adapter and discarded, which read as agreement with the panel while being no
#: such thing (issue #68).
_ANALYSIS_MODEL = analysis_model()

#: The founder gate — verifies the shared-Cognito JWT and requires the group. The
#: verified user carries its raw token, forwarded to Core by the transport.
require_founder = require_group("founder")


def get_service(founder: ForwardedUser = Depends(require_founder)) -> IdeationService:
    """One :class:`IdeationService` per request, bound to Core over a transport that
    signs as this Lambda AND forwards *this* founder's token."""
    transport = CoreTransport(founder_token=founder.token)
    return IdeationService(CoreHttpGateway(transport), analysis_model=_ANALYSIS_MODEL)


app = FastAPI(title="Ideation Engine", docs_url=None, redoc_url=None)

# Orchestration errors → HTTP. Registered once for the base class; the map keys on
# the concrete type. Anything unmapped is a 400 (a bad request the founder can fix).
_ERROR_STATUS: dict[type[IdeationError], int] = {
    SessionNotFoundError: 404,
    NotGatheringError: 409,
    TurnLimitReachedError: 409,
    NotEnoughTurnsError: 422,
    AnalysisFailedError: 502,
    MalformedReportError: 502,
}


@app.exception_handler(IdeationError)
async def _on_ideation_error(_: Request, exc: IdeationError) -> JSONResponse:
    status = _ERROR_STATUS.get(type(exc), 400)
    return JSONResponse(status_code=status, content={"detail": str(exc) or type(exc).__name__})


class StartSessionRequest(BaseModel):
    seed_idea: str = Field(min_length=1, max_length=16_000)
    #: Which active challenger to use — omitted (or null) falls back to the
    #: built-in seed challenger. Never trusted as anything but a lookup key;
    #: Core resolves the actual prompt server-side (ADR-0016 §1).
    challenger_agent_key: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)


@app.get("/sessions")
async def list_sessions(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> list[dict]:
    """Every past run for this founder, most-recent-first — for the session nav."""
    sessions = await svc.list_sessions(owner_sub=founder.sub)
    return [_summary(s) for s in sessions]


@app.get("/submitted-idea")
async def get_submitted_idea(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """The founder's own early-access idea submission, if any — for the
    seed-idea prefill affordance. ``idea`` is null if they never submitted one."""
    idea = await svc.get_submitted_idea(owner_sub=founder.sub)
    return {"idea": idea}


@app.get("/agents")
async def list_agents(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> list[dict]:
    """The active challenger roster for the seed view's persona picker.
    agent_key/agent_name only — never system_prompt (ADR-0016 §1: an
    unprivileged caller never sees prompt text, even read-only)."""
    return await svc.list_active_challengers()


def _derive_title(seed_idea: str, *, max_len: int = 60) -> str:
    """A display title from the seed idea when none was explicitly set: trim to
    ~max_len chars at a word boundary, with an ellipsis if truncated."""
    stripped = seed_idea.strip()
    if len(stripped) <= max_len:
        return stripped
    # Truncate to max_len, then back up to the last space to avoid cutting a word
    truncated = stripped[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space] + "…"
    # No space found within max_len; hard-truncate and add ellipsis
    return truncated + "…"


def _state(session) -> dict:  # type: ignore[no-untyped-def]
    return {
        "session_id": session.id,
        "status": session.status,
        "turn_count": session.turn_count,
        "min_turns": MIN_TURNS,
        "max_turns": MAX_TURNS,
        "can_finalise": session.status == GATHERING and session.turn_count >= MIN_TURNS,
    }


def _summary(session) -> dict:  # type: ignore[no-untyped-def]
    return {
        "session_id": session.id,
        "title": session.title or _derive_title(session.seed_idea),
        "status": session.status,
        "created_at": session.created_at,
    }


@app.post("/sessions", status_code=201)
async def start_session(
    body: StartSessionRequest,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> dict:
    """Open a session for the founder's idea and run the first challenger turn (the
    idea is turn 1's fenced message). Returns the challenger's opening reply."""
    session = await svc.start_session(
        owner_sub=founder.sub,
        seed_idea=body.seed_idea,
        challenger_agent_key=body.challenger_agent_key,
    )
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


@app.post("/sessions/{session_id}/delete", status_code=204)
async def delete_session(
    session_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeationService = Depends(get_service),
) -> None:
    """Soft-delete a session — deletable regardless of status."""
    await svc.delete_session(owner_sub=founder.sub, session_id=session_id)


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
