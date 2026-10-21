from fastapi import APIRouter

from app.platform.api import agent_api, auth_api, comms_api, dashboard_api, ndr_api, ops_api, system_api

router = APIRouter()
for module in (auth_api, dashboard_api, ndr_api, agent_api, comms_api, ops_api, system_api):
    router.include_router(module.router)
