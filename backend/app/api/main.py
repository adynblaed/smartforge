from fastapi import APIRouter

from app.api.routes import (
    alerts,
    askai,
    command_center,
    customer,
    datasources,
    factory,
    incidents,
    integrations,
    items,
    login,
    logs,
    machines,
    planning,
    private,
    services,
    sops,
    supply_chain,
    tickets,
    users,
    utils,
    work_orders,
    ws,
)
from app.core.config import settings

api_router = APIRouter()
# Template core
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)

# SmartForge modules
api_router.include_router(machines.router)
api_router.include_router(alerts.router)
api_router.include_router(work_orders.router)
api_router.include_router(tickets.router)
api_router.include_router(sops.router)
api_router.include_router(askai.router)
api_router.include_router(factory.router)
api_router.include_router(integrations.router)
api_router.include_router(incidents.router)
api_router.include_router(planning.router)
api_router.include_router(supply_chain.router)
api_router.include_router(customer.router)
api_router.include_router(command_center.router)
api_router.include_router(datasources.router)
api_router.include_router(services.router)
api_router.include_router(logs.router)
api_router.include_router(ws.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
