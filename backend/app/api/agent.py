from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.agent.provider import AgentService
from app.agent.voice import MockVoiceProvider, VoiceAgent
from app.db import get_db

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/agent/message", response_model=schemas.AgentMessageOut)
async def agent_message(body: schemas.AgentMessageIn, db: Session = Depends(get_db)):
    """Mock WhatsApp endpoint. A real WhatsApp webhook would parse the inbound message, call
    AgentService.handle(...) exactly like this, and then send `reply` back through the WhatsApp provider."""
    reply, calls = await AgentService(db).handle(
        body.conversation_id, body.message, body.customer_name, body.customer_phone
    )
    return schemas.AgentMessageOut(reply=reply, tool_calls=calls)


@router.post("/voice/mock-call")
async def mock_call(body: schemas.MockCallIn, db: Session = Depends(get_db)):
    """Runs a scripted phone call through the same agent + tools, using MockVoiceProvider."""
    provider = MockVoiceProvider(body.utterances)
    call_id = f"call-{abs(hash(tuple(body.utterances))) % 10**8}"
    await VoiceAgent(provider, AgentService(db)).run_call(call_id, body.caller_phone)
    return {"callId": call_id, "transcript": provider.transcript}
