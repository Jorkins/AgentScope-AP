import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_blob_backend_is_minio_s3():
    settings = Settings(
        _env_file=None,
        JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    )

    assert settings.BLOB_BACKEND == "s3"


@pytest.mark.parametrize(
    "secret",
    [
        "change-me-to-a-long-random-string",
        "too-short",
    ],
)
def test_production_auth_rejects_weak_jwt_secret(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(
            _env_file=None,
            AUTH_ENABLED=True,
            JWT_SECRET=secret,
        )
