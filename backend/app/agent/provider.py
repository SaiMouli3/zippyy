"""Agent provider abstraction + conversation plumbing.

Swap RuleBasedAgentProvider for an LLM-backed provider by implementing `respond` and registering it in
`get_agent_provider`. The provider only talks to Zippy through `ZippyTools`.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.tools import ZippyTools
from app.cache import cache_get_json, cache_set_json
from app.config import get_settings


@dataclass
class Conversation:
    id: str
    state: dict = field(default_factory=dict)  # provider-owned scratch space
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"assistant", "text": ...}]
    customer_name: str = "WhatsApp Customer"
    customer_phone: str = "+919999999999"


class AgentProvider(ABC):
    @abstractmethod
    async def respond(self, conversation: Conversation, message: str, tools: ZippyTools) -> str:
        """Produce the reply text for one user message, calling tools as needed."""


def get_agent_provider() -> AgentProvider:
    name = get_settings().agent_provider
    if name == "rule_based":
        from app.agent.rule_based import RuleBasedAgentProvider

        return RuleBasedAgentProvider()
    raise ValueError(f"unknown AGENT_PROVIDER '{name}'")  # e.g. register an LLM provider here


class AgentService:
    """Loads/saves conversation state (Redis) around a provider call. Used by WhatsApp and voice alike."""

    TTL = 24 * 3600

    def __init__(self, db: Session, provider: AgentProvider | None = None):
        self.db = db
        self.provider = provider or get_agent_provider()

    async def handle(self, conversation_id: str, message: str, customer_name=None, customer_phone=None) -> tuple[str, list[dict]]:
        key = f"zippy:conv:{conversation_id}"
        saved = await cache_get_json(key)
        conv = Conversation(**saved) if saved else Conversation(id=conversation_id)
        if customer_name:
            conv.customer_name = customer_name
        if customer_phone:
            conv.customer_phone = customer_phone

        tools = ZippyTools(self.db)
        conv.history.append({"role": "user", "text": message})
        reply = await self.provider.respond(conv, message, tools)
        conv.history.append({"role": "assistant", "text": reply})
        conv.history = conv.history[-50:]

        await cache_set_json(key, {
            "id": conv.id, "state": conv.state, "history": conv.history,
            "customer_name": conv.customer_name, "customer_phone": conv.customer_phone,
        }, self.TTL)
        return reply, tools.calls
