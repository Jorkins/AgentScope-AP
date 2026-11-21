from scripts.verify_stack import redact_secret


def test_dependency_errors_do_not_expose_credentials():
    message = (
        "postgresql+asyncpg://ap:secret@localhost/db; "
        "token=root:secret; http://user:secret@minio:9000"
    )

    redacted = redact_secret(message)

    assert "secret" not in redacted
    assert "postgresql+asyncpg://ap:***@localhost/db" in redacted
    assert "token=***" in redacted
