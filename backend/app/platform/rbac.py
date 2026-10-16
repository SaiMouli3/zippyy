"""Role-based access control. Roles are per merchant (memberships.role); permissions are code-defined so a
deploy, not a database edit, changes what a role can do."""

PERMISSIONS = {
    "dashboard.read", "ndr.read", "ndr.act", "ndr.resolve", "shipments.read", "shipments.import",
    "conversations.read", "transcripts.read", "recordings.read", "pii.unmask", "agent_runs.read", "agent_runs.retry",
    "carrier_actions.read", "carrier_actions.reconcile", "escalations.read", "escalations.act",
    "escalations.approve", "escalations.supervise", "analytics.read", "integrations.read", "integrations.manage",
    "agent_config.read", "agent_config.write", "policies.read", "policies.write", "audit.read", "settings.read",
    "settings.write", "users.manage", "api_keys.manage", "export.csv", "preferences.correct",
}

_READ = {
    "dashboard.read", "ndr.read", "shipments.read", "conversations.read", "agent_runs.read", "carrier_actions.read",
    "escalations.read", "analytics.read", "integrations.read", "agent_config.read", "policies.read", "settings.read",
}
_OPS = _READ | {
    "ndr.act", "ndr.resolve", "transcripts.read", "agent_runs.retry", "carrier_actions.reconcile", "escalations.act",
    "export.csv", "preferences.correct",
}
_OPS_LEAD = _OPS | {"escalations.approve", "escalations.supervise", "pii.unmask", "recordings.read", "audit.read"}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset(_READ),
    "finance": frozenset(_READ | {"export.csv", "audit.read"}),
    "ops": frozenset(_OPS),
    "ops_lead": frozenset(_OPS_LEAD),
    "owner": frozenset(PERMISSIONS),
}

# API keys (server-to-server) get explicit scopes, never a role.
API_KEY_SCOPES = {"shipments.import", "shipments.read", "ndr.read", "events.ingest"}


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())
