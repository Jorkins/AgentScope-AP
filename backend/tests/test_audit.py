import logging

import httpx
import pytest

from app.platform.audit import RequestAuditMiddleware


async def ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_audit_logs_request_id_without_credentials_or_body(caplog):
    app = RequestAuditMiddleware(ok_app)
    caplog.set_level(logging.INFO, logger="agentscope_ap.audit")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/platform/auth/login?password=query-secret",
            content="body-secret",
            headers={
                "Authorization": "Bearer token-secret",
                "X-Request-ID": "req-test-123",
            },
        )

    assert response.headers["x-request-id"] == "req-test-123"
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "req-test-123" in logs
    assert "/api/platform/auth/login" in logs
    assert "200" in logs
    assert "query-secret" not in logs
    assert "body-secret" not in logs
    assert "token-secret" not in logs
