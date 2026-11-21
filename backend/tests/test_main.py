from fastapi.middleware.cors import CORSMiddleware

from app import main
from app.platform.audit import RequestAuditMiddleware


def test_main_uses_shared_runtime_and_disables_background_owners():
    assert main.app.state.storage is main.runtime.storage
    assert main.app.state.message_bus is main.runtime.message_bus
    assert main.app.state.workspace_manager is main.runtime.workspace_manager
    assert main.app.state.knowledge_base_manager is main.runtime.knowledge_base_manager
    assert main.app.state.blob_store is main.runtime.blob_store
    assert main.app.state.enable_index_worker is False
    assert main.app.state.enable_channel_worker is False
    assert main.app.state.enable_scheduler is False


def test_main_includes_request_audit_middleware():
    assert any(
        middleware.cls is RequestAuditMiddleware
        for middleware in main.app.user_middleware
    )


def test_main_uses_explicit_cors_origins():
    cors = next(
        middleware
        for middleware in main.app.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert cors.kwargs["allow_origins"] == main.settings.cors_origin_list
    assert "*" not in cors.kwargs["allow_origins"]
    assert cors.kwargs["allow_methods"] == main.settings.cors_method_list
    assert cors.kwargs["allow_headers"] == main.settings.cors_header_list
