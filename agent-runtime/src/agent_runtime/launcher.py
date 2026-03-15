"""Agent subprocess launch and supervision."""

import asyncio
import os
import subprocess

from agent_runtime.config import write_agent_configs


class AgentProcess:
    """Wraps a Claude CLI subprocess for a single mesh agent."""

    def __init__(
        self,
        uuid: str,
        model: str,
        agent_dir: str,
        bearer_token: str,
        thinking_budget: int | None = None,
        initial_prompt: str | None = None,
    ):
        if not model:
            raise ValueError("model must be a non-empty string")

        self._uuid = uuid
        self._model = model
        self._agent_dir = agent_dir
        self._bearer_token = bearer_token
        self._thinking_budget = thinking_budget
        self._initial_prompt = initial_prompt
        self._process: subprocess.Popen | None = None

    @property
    def pid(self) -> int | None:
        """Return the PID of the subprocess, or None if not started."""
        return self._process.pid if self._process else None

    def _build_env(self) -> dict:
        """Build environment variables for the subprocess.

        INV-8: Sets MESH_AGENT_ID, MESH_BEARER_TOKEN, MESH_DATA_DIR.
        """
        env = os.environ.copy()
        env["MESH_AGENT_ID"] = self._uuid
        env["MESH_BEARER_TOKEN"] = self._bearer_token
        env["MESH_DATA_DIR"] = self._agent_dir
        return env

    def _build_cli_args(self) -> list[str]:
        """Build CLI arguments for the claude command.

        INV-4: Model names translate to correct CLI flags.
        """
        mcp_config_path = os.path.join(self._agent_dir, "mcp_config.json")

        args = [
            "claude",
            "--model",
            self._model,
            "--mcp-config",
            mcp_config_path,
        ]

        if self._thinking_budget is not None:
            args.extend(["--thinking-budget", str(self._thinking_budget)])

        if self._initial_prompt is not None:
            args.extend(["-p", self._initial_prompt])

        return args

    def start(self) -> int:
        """Launch the Claude CLI subprocess. Returns PID."""
        env = self._build_env()
        args = self._build_cli_args()

        self._process = subprocess.Popen(
            args,
            env=env,
            cwd=self._agent_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return self._process.pid

    def wait(self) -> int:
        """Wait for the subprocess to exit. Returns exit code."""
        if self._process is None:
            raise RuntimeError("Process not started")
        return self._process.wait()


class AgentSupervisor:
    """Manages multiple agent processes with supervision."""

    def __init__(self, shutdown_callback=None):
        """Initialize supervisor.

        Args:
            shutdown_callback: async function(uuid, exit_code) called when agent exits
                without explicit shutdown.
        """
        self._shutdown_callback = shutdown_callback
        self._processes: dict[str, AgentProcess] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def active_agents(self) -> dict[str, AgentProcess]:
        """Return dict of active agent UUIDs to their processes."""
        return dict(self._processes)

    def get_process(self, uuid: str) -> AgentProcess | None:
        """Get the AgentProcess for a given UUID."""
        return self._processes.get(uuid)

    async def launch(
        self,
        uuid: str,
        model: str,
        agent_dir: str,
        bearer_token: str,
        spawner_uuid: str,
        server_url: str,
        server_base_url: str,
        role: str | None,
        thinking_budget: int | None = None,
        initial_prompt: str | None = None,
    ) -> int:
        """Write configs, start process, and begin supervision.

        Returns the PID of the launched process.
        """
        # Write all config files
        write_agent_configs(
            agent_dir=agent_dir,
            agent_uuid=uuid,
            spawner_uuid=spawner_uuid,
            bearer_token=bearer_token,
            model=model,
            server_url=server_url,
            server_base_url=server_base_url,
            role=role,
        )

        # Create and start the process
        process = AgentProcess(
            uuid=uuid,
            model=model,
            agent_dir=agent_dir,
            bearer_token=bearer_token,
            thinking_budget=thinking_budget,
            initial_prompt=initial_prompt,
        )
        pid = process.start()

        self._processes[uuid] = process

        # Start supervision task
        task = asyncio.create_task(self._supervise(uuid))
        self._tasks[uuid] = task

        return pid

    async def _supervise(self, uuid: str) -> None:
        """Wait for process exit and call shutdown callback if needed."""
        process = self._processes.get(uuid)
        if process is None:
            return

        # Wait for exit in a thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        exit_code = await loop.run_in_executor(None, process.wait)

        # Clean up
        self._processes.pop(uuid, None)
        self._tasks.pop(uuid, None)

        # Notify via callback
        if self._shutdown_callback:
            await self._shutdown_callback(uuid, exit_code)
