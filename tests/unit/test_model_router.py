"""Unit tests for the Model Router."""

import pytest

from services.contracts.models import ModelRequest, ModelResponse
from services.model_router import MockProvider, ModelRouter


@pytest.fixture
def router() -> ModelRouter:
    r = ModelRouter()
    r.register_provider(MockProvider())
    r.set_role_routing("FAST_INTENT", "mock")
    r.set_role_routing("LOCAL_DIALOG", "mock")
    return r


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_mock_generates_response(self):
        provider = MockProvider()
        request = ModelRequest(
            role="FAST_INTENT",
            messages=[{"role": "user", "content": "Hello"}],
        )
        response = await provider.generate(request)
        assert response.provider == "mock"
        assert len(response.content) > 0
        assert response.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_mock_health(self):
        provider = MockProvider()
        health = await provider.health()
        assert health["status"] == "healthy"


class TestModelRouter:
    @pytest.mark.asyncio
    async def test_routes_to_configured_provider(self, router: ModelRouter):
        request = ModelRequest(
            role="FAST_INTENT",
            messages=[{"role": "user", "content": "Test"}],
        )
        response = await router.route(request)
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_tracks_costs(self, router: ModelRouter):
        request = ModelRequest(
            role="LOCAL_DIALOG",
            messages=[{"role": "user", "content": "Count costs"}],
        )
        await router.route(request)
        health = await router.health()
        assert health["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_unconfigured_role_falls_back(self, router: ModelRouter):
        request = ModelRequest(
            role="UNKNOWN_ROLE",
            messages=[{"role": "user", "content": "Fallback test"}],
        )
        response = await router.route(request)
        assert response.provider == "mock"
