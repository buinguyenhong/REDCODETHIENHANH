from app.models import IntegrationSettings


async def get_integration(session):
    row = await session.get(IntegrationSettings, 1)
    # New installations are disabled; existing env URL is not auto-enabled.
    return row
