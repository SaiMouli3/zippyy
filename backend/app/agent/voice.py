"""Voice channel abstraction. A real provider (Twilio Voice, Exotel, Plivo, LiveKit...) implements VoiceProvider;
the conversation logic (VoiceAgent) is provider-independent and reuses the same AgentService/tools as WhatsApp.
"""
from abc import ABC, abstractmethod

from app.agent.provider import AgentService


class VoiceProvider(ABC):
    @abstractmethod
    async def handle_incoming_call(self, call_id: str, caller: str | None) -> None: ...

    @abstractmethod
    async def speak(self, call_id: str, text: str) -> None: ...

    @abstractmethod
    async def collect_input(self, call_id: str) -> str | None:
        """Return the caller's next utterance (speech-to-text), or None if the caller hung up / said nothing."""

    @abstractmethod
    async def end_call(self, call_id: str) -> None: ...


class MockVoiceProvider(VoiceProvider):
    """Scripted caller. `transcript` records both sides so it can be returned from an API or asserted in tests."""

    def __init__(self, utterances: list[str]):
        self._inputs = list(utterances)
        self.transcript: list[dict] = []
        self.ended = False

    async def handle_incoming_call(self, call_id: str, caller: str | None) -> None:
        self.transcript.append({"role": "system", "text": f"incoming call {call_id} from {caller or 'unknown'}"})

    async def speak(self, call_id: str, text: str) -> None:
        self.transcript.append({"role": "agent", "text": text})

    async def collect_input(self, call_id: str) -> str | None:
        if not self._inputs:
            return None
        text = self._inputs.pop(0)
        self.transcript.append({"role": "caller", "text": text})
        return text

    async def end_call(self, call_id: str) -> None:
        self.ended = True
        self.transcript.append({"role": "system", "text": "call ended"})


class VoiceAgent:
    def __init__(self, provider: VoiceProvider, agent: AgentService):
        self.provider, self.agent = provider, agent

    async def run_call(self, call_id: str, caller: str | None = None) -> None:
        await self.provider.handle_incoming_call(call_id, caller)
        await self.provider.speak(call_id, "Welcome to Zippy. How can I help you today?")
        while (heard := await self.provider.collect_input(call_id)) is not None:
            reply, _ = await self.agent.handle(f"voice:{call_id}", heard, customer_phone=caller)
            await self.provider.speak(call_id, reply)
        await self.provider.end_call(call_id)
