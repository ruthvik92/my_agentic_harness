"""Netlist request must freeze phone-v1 tools empty even when the server
starts with a browser/coder config; selected model/provider/budgets/limits
must survive normalization."""

from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.mobile.web import BrowserServer

CONFIG_NAMES = ["browser.yaml", "coder.yaml"]


def test_netlist_freezes_phone_v1_tools_and_preserves_selection(
    tmp_path, monkeypatch, config_name
):
    captured = {}

    def fake_runner(request: Path):
        # load_config validates the instructions hash of the frozen request.
        captured["config"] = load_config(request.with_name("config.json"))
        return {
            "status": "completed_unverified",
            "answer": "Netlist stub",
            "run_id": None,
            "audit": {"ok": True},
        }

    server = BrowserServer(
        tmp_path / "state",
        Path("config") / config_name,
        host="127.0.0.1",
        port=0,
        runner=fake_runner,
    )
    try:
        # Prevent model discovery; selection falls back to the server config.
        monkeypatch.setattr(
            server.models,
            "select",
            lambda model_id=None, has_image=False: (server.config, {}),
        )

        thread_id = server.threads.create("netlist")
        server.threads.update(
            thread_id,
            messages=[
                {"role": "user", "content": "Generate the netlist."},
                {
                    "role": "assistant",
                    "content": "Here is the netlist.",
                    "kind": "answer",
                    "has_image": True,
                },
            ],
        )

        job_id = server.submit_thread(thread_id, {}, kind="netlist")
        server.jobs.pending.join()
        job = server.jobs.get(job_id)

        assert job["status"] == "completed"

        frozen = captured["config"]
        assert frozen.instructions_version == "phone-v1"
        assert frozen.tools == ()

        # Selection must survive normalization.
        assert frozen.model == server.config.model
        assert frozen.provider == server.config.provider
        assert frozen.window_tokens == server.config.window_tokens
        assert frozen.output_reserve_tokens == server.config.output_reserve_tokens
        assert frozen.limits == server.config.limits
    finally:
        server.server_close()


@pytest.fixture(params=CONFIG_NAMES)
def config_name(request):
    return request.param
