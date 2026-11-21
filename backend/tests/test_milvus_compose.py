from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_compose_runs_dedicated_authenticated_milvus_and_parks_qdrant():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["milvus"]["image"] == "milvusdb/milvus:v2.6.13"
    assert services["milvus"]["container_name"] == "ap-milvus"
    assert services["milvus"]["depends_on"]["milvus-etcd"]["condition"] == "service_healthy"
    assert services["milvus"]["environment"]["COMMON_SECURITY_AUTHORIZATIONENABLED"] == "true"
    assert services["milvus"]["environment"]["COMMON_SECURITY_DEFAULTROOTPASSWORD"] == "${MILVUS_ROOT_PASSWORD:-root}"
    assert "19530:19530" in services["milvus"]["ports"]
    assert "milvus" not in compose.get("networks", {})
    assert services["qdrant"]["profiles"] == ["legacy"]
    assert "qdrantdata" in compose["volumes"]
    assert "milvusdata" in compose["volumes"]
    assert "milvusetcd" in compose["volumes"]


def test_env_example_targets_dedicated_milvus():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VECTOR_BACKEND=milvus" in env_example
    assert "MILVUS_URI=http://localhost:19530" in env_example
    assert "MILVUS_TOKEN=root:root" in env_example
    assert "MILVUS_ROOT_PASSWORD=root" in env_example
