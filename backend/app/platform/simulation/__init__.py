"""Simulated providers' asynchronous behaviour (demo merchants, development and tests only).

Each simulator emulates what the real provider would do *after* an API call — status callbacks, a customer's
reply, a call conversation, a carrier's later scans — and delivers it as a signed webhook through the same
ingestion code path as production. Behaviour comes from `simulation_profiles`; nothing here is consulted by
business logic.
"""
