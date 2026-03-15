"""Tests for agent_runtime.launcher — INV-4, INV-8, FAIL-1."""

from agent_runtime.launcher import AgentProcess


AGENT_UUID = "abcd1234-0000-0000-0000-000000000001"
AGENT_DIR = "/tmp/test-agent-dir"
BEARER_TOKEN = "secret-token-123"


class TestInv8EnvVarInjection:
    """INV-8: Environment variables are set correctly for subprocess."""

    def test_inv8_env_var_injection(self):
        proc = AgentProcess(
            uuid=AGENT_UUID,
            model="sonnet",
            agent_dir=AGENT_DIR,
            bearer_token=BEARER_TOKEN,
        )
        env = proc._build_env()

        assert env["MESH_AGENT_ID"] == AGENT_UUID
        assert env["MESH_BEARER_TOKEN"] == BEARER_TOKEN
        assert env["MESH_DATA_DIR"] == AGENT_DIR
        # Should also inherit PATH from parent env
        assert "PATH" in env


class TestInv4ModelToCliArgs:
    """INV-4: Model names translate to correct CLI flags."""

    def test_inv4_model_to_cli_args(self):
        proc = AgentProcess(
            uuid=AGENT_UUID,
            model="sonnet",
            agent_dir=AGENT_DIR,
            bearer_token=BEARER_TOKEN,
            thinking_budget=10000,
        )
        args = proc._build_cli_args()

        assert "claude" in args[0]
        assert "--model" in args
        model_idx = args.index("--model")
        assert args[model_idx + 1] == "sonnet"
        assert "--mcp-config" in args
        assert "--thinking-budget" in args
        tb_idx = args.index("--thinking-budget")
        assert args[tb_idx + 1] == "10000"

    def test_inv4_no_thinking_budget(self):
        proc = AgentProcess(
            uuid=AGENT_UUID,
            model="sonnet",
            agent_dir=AGENT_DIR,
            bearer_token=BEARER_TOKEN,
        )
        args = proc._build_cli_args()

        assert "--model" in args
        assert "--thinking-budget" not in args

    def test_inv4_initial_prompt(self):
        proc = AgentProcess(
            uuid=AGENT_UUID,
            model="sonnet",
            agent_dir=AGENT_DIR,
            bearer_token=BEARER_TOKEN,
            initial_prompt="Hello mesh",
        )
        args = proc._build_cli_args()

        assert "-p" in args
        p_idx = args.index("-p")
        assert args[p_idx + 1] == "Hello mesh"


class TestFail1InvalidModel:
    """FAIL-1: Invalid model string rejected."""

    def test_fail1_invalid_model_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            AgentProcess(
                uuid=AGENT_UUID,
                model="",
                agent_dir=AGENT_DIR,
                bearer_token=BEARER_TOKEN,
            )

    def test_fail1_none_model_rejected(self):
        import pytest

        with pytest.raises((ValueError, TypeError)):
            AgentProcess(
                uuid=AGENT_UUID,
                model=None,
                agent_dir=AGENT_DIR,
                bearer_token=BEARER_TOKEN,
            )
