"""Row-level security and database roles.

* Every tenant table gets a FORCED RLS policy: rows are visible/writable only when
  merchant_id = current_setting('app.merchant_id'), or when the transaction runs in system context
  (app.system = 'on', used only by ingestion, the job claimer and schedulers). FORCE applies the policy to the
  table owner too, so a misconfigured deployment that connects as the owner is still isolated.
* `zippy_app` (NOLOGIN group role) receives DML on application tables but no UPDATE/DELETE on append-only
  history (audit logs, agent steps, call events, message status events, carrier action events). Production
  should connect with a LOGIN role that is a member of zippy_app and is *not* the table owner.
  Role creation is skipped (with a notice) when the migrating user lacks CREATEROLE; a DBA can then create it.

Revision ID: 0003_rls_and_roles
"""
from alembic import op

revision = "0003_rls_and_roles"
down_revision = "0002_platform"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "api_keys", "merchant_settings", "policy_versions", "customers", "addresses", "consent_records",
    "simulation_profiles", "delivery_attempts", "ndr_cases", "conversations", "message_templates", "messages",
    "message_status_events", "voice_calls", "voice_call_events", "intent_extractions", "rule_decisions",
    "carrier_actions", "carrier_action_events", "escalations", "escalation_notes", "delivery_preferences",
    "agent_tasks", "agent_runs", "agent_run_steps", "contact_attempts", "delivery_outcomes", "outbox_events",
    "idempotency_keys", "orders", "shipments", "shipment_events", "audit_logs",
)
APPEND_ONLY = ("audit_logs", "agent_run_steps", "voice_call_events", "message_status_events", "carrier_action_events")
CONDITION = ("(merchant_id = current_setting('app.merchant_id', true) "
             "OR current_setting('app.system', true) = 'on')")


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING {CONDITION} WITH CHECK {CONDITION}")
    op.execute("ALTER TABLE merchants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE merchants FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON merchants")
    op.execute("CREATE POLICY tenant_isolation ON merchants USING (id = current_setting('app.merchant_id', true) "
               "OR current_setting('app.system', true) = 'on')")

    revoke = "; ".join(f"REVOKE UPDATE, DELETE ON {t} FROM zippy_app" for t in APPEND_ONLY)
    op.execute(f"""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zippy_app') THEN
        BEGIN
          CREATE ROLE zippy_app NOLOGIN;
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'zippy_app role not created (no CREATEROLE); ask a DBA to create it and re-run grants';
          RETURN;
        END;
      END IF;
      GRANT USAGE ON SCHEMA public TO zippy_app;
      GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO zippy_app;
      GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO zippy_app;
      {revoke};
      REVOKE ALL ON alembic_version FROM zippy_app;
      GRANT SELECT ON alembic_version TO zippy_app;
      BEGIN
        -- Lets the migrating user verify the role (SET ROLE zippy_app); production login roles get it from a DBA.
        EXECUTE format('GRANT zippy_app TO %I', current_user);
      EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'could not grant zippy_app membership to %', current_user;
      END;
    END $$;
    """)


def downgrade() -> None:
    for table in (*TENANT_TABLES, "merchants"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
