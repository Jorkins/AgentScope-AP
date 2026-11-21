from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_minio_uses_pinned_images_and_separate_application_credentials():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["minio"]["image"] == (
        "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/minio/"
        "minio:RELEASE.2025-09-07T16-13-09Z"
    )
    assert services["minio-init"]["image"] == (
        "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/minio/"
        "mc:RELEASE.2025-08-13T08-35-41Z"
    )
    assert "MINIO_ROOT_USER" in services["minio"]["environment"]
    assert services["minio"]["environment"]["MINIO_ROOT_USER"] != "${S3_ACCESS_KEY:-ap_minio}"
    assert services["minio-init"]["depends_on"]["minio"]["condition"] == "service_healthy"


def test_minio_init_creates_private_bucket_and_least_privilege_policy():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = services_command = compose["services"]["minio-init"]["entrypoint"]
    command_text = " ".join(services_command) if isinstance(command, list) else str(command)
    policy = yaml.safe_load((ROOT / "deploy/minio/policy.json").read_text(encoding="utf-8"))

    assert "mb --ignore-existing" in command_text
    assert "anonymous set none" in command_text
    assert "admin user add" in command_text
    assert "admin policy attach" in command_text
    assert "sed " not in command_text
    assert "while IFS= read -r line" in command_text
    statements = policy["Statement"]
    assert all("s3:*" not in statement["Action"] for statement in statements)
    assert not any("arn:aws:s3:::*" in statement["Resource"] for statement in statements)
