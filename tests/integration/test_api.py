"""Integration tests for the Core API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from services.core_api.app import create_app


@pytest.fixture
async def client():
    app = create_app()

    # Manually trigger lifespan for test
    from services.core_api.state import AppState
    state = AppState()
    await state.initialize()
    app.state.jarvis = state

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await state.shutdown()


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "services" in data

    @pytest.mark.asyncio
    async def test_list_models(self, client: AsyncClient):
        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_tools(self, client: AsyncClient):
        resp = await client.get("/api/v1/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert len(tools) >= 1
        assert tools[0]["tool_id"] == "sandbox.files"

    @pytest.mark.asyncio
    async def test_privacy_status(self, client: AsyncClient):
        resp = await client.get("/api/v1/privacy/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["microphone"] == "off"
        assert data["cloud_streaming"] == "off"


class TestTaskEndpoints:
    @pytest.mark.asyncio
    async def test_create_task(self, client: AsyncClient):
        resp = await client.post("/api/v1/tasks", json={
            "input_text": "List sandbox files"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CREATED"
        assert "task_id" in data

    @pytest.mark.asyncio
    async def test_get_task(self, client: AsyncClient):
        create_resp = await client.post("/api/v1/tasks", json={
            "input_text": "Test retrieval"
        })
        task_id = create_resp.json()["task_id"]

        get_resp = await client.get(f"/api/v1/tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, client: AsyncClient):
        resp = await client.get("/api/v1/tasks/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tasks(self, client: AsyncClient):
        await client.post("/api/v1/tasks", json={"input_text": "Task A"})
        await client.post("/api/v1/tasks", json={"input_text": "Task B"})

        resp = await client.get("/api/v1/tasks")
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) >= 2

    @pytest.mark.asyncio
    async def test_run_task(self, client: AsyncClient):
        create_resp = await client.post("/api/v1/tasks", json={
            "input_text": "List all files in the sandbox"
        })
        task_id = create_resp.json()["task_id"]

        run_resp = await client.post(f"/api/v1/tasks/{task_id}/run")
        assert run_resp.status_code == 200
        data = run_resp.json()
        assert data["status"] in ("COMPLETED", "FAILED")

    @pytest.mark.asyncio
    async def test_cancel_task(self, client: AsyncClient):
        create_resp = await client.post("/api/v1/tasks", json={
            "input_text": "Task to cancel"
        })
        task_id = create_resp.json()["task_id"]

        cancel_resp = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_task_events(self, client: AsyncClient):
        create_resp = await client.post("/api/v1/tasks", json={
            "input_text": "Observe events"
        })
        task_id = create_resp.json()["task_id"]
        await client.post(f"/api/v1/tasks/{task_id}/run")

        events_resp = await client.get(f"/api/v1/tasks/{task_id}/events")
        assert events_resp.status_code == 200
        events = events_resp.json()
        assert len(events) >= 1
