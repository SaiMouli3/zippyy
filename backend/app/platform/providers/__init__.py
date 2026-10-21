"""External provider adapters (WhatsApp, voice, Sarvam speech/LLM). Each has a live implementation built from
the provider's official API documentation and a simulator for development, tests and demo merchants.

Selection is explicit (`WHATSAPP_PROVIDER`, `VOICE_PROVIDER`). Demo merchants always get simulators; in
production a non-demo merchant never silently falls back to a simulator.
"""
