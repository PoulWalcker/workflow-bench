"""Native Harbor job configuration for the direct Codex controls."""

from pathlib import Path

import yaml
from harbor.agents.factory import AgentFactory
from harbor.models.job.config import JobConfig

from workflow_bench.composer import SessionSafeCodex


def test_example_builds_pinned_direct_agent_without_ambient_credentials(
    tmp_path: Path,
) -> None:
    config = JobConfig.model_validate(
        yaml.safe_load(Path("examples/codex/job.yaml").read_text())
    )
    agent = AgentFactory.create_agent_from_config(config.agents[0], logs_dir=tmp_path)
    assert isinstance(agent, SessionSafeCodex)
    assert agent.model_name == "openai/gpt-6.1-sol"
    assert agent.version() == "0.162.1"
    assert agent.options.reasoning_effort == "low"
    assert agent.mcp_servers == []
    assert isinstance(agent.config_source, dict)
    assert agent.config_source["model_provider"] == "empty"
    assert config.agents[0].env == {
        "CODEX_AUTH_JSON_PATH": "",
        "CODEX_FORCE_AUTH_JSON": "FALSE",
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "",
    }
    assert config.n_attempts == 1
    assert config.retry.max_retries == 0
    assert (
        config.environment.import_path
        == "workflow_bench.harbor:DeadlineDockerEnvironment"
    )
