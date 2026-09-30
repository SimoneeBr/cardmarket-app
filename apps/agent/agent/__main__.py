"""Agent CLI.

python -m agent run              # main loop (default)
python -m agent pair             # local, headed pairing without the API
python -m agent check-session    # print the persisted session state
python -m agent calibrate        # read-only selector health check (live)
"""

import argparse
import asyncio
import json
import logging
import sys

from cmc_shared.logging import configure_logging

from agent.adapter import CardmarketAdapter
from agent.config import AgentSettings, get_settings

log = logging.getLogger("cmc.agent")


def build_adapter(settings: AgentSettings) -> CardmarketAdapter:
    if settings.mock_cardmarket:
        from agent.mock.adapter import MockCardmarketAdapter

        return MockCardmarketAdapter(settings)
    from agent.cardmarket.adapter import PlaywrightCardmarketAdapter

    return PlaywrightCardmarketAdapter(settings)


async def _run(settings: AgentSettings) -> int:
    from agent.api_client import ApiClient
    from agent.runner import AgentRunner

    token = settings.agent_api_token.get_secret_value()
    if not token:
        log.error("AGENT_API_TOKEN is not set")
        return 2
    runner = AgentRunner(settings, ApiClient(settings.api_url, token), build_adapter(settings))
    await runner.run()
    return 0


async def _pair(settings: AgentSettings) -> int:
    adapter = build_adapter(settings)
    await adapter.start()
    try:
        state = await adapter.pair(settings.pairing_timeout_seconds)
    finally:
        await adapter.close()
    print(json.dumps({"status": str(state.status), "message": state.message}))
    return 0 if state.connected else 1


async def _check(settings: AgentSettings) -> int:
    adapter = build_adapter(settings)
    await adapter.start()
    try:
        state = await adapter.check_session()
    finally:
        await adapter.close()
    print(
        json.dumps(
            {"status": str(state.status), "message": state.message, "error_code": state.error_code}
        )
    )
    return 0 if state.connected else 1


async def _calibrate(settings: AgentSettings) -> int:
    from agent.cardmarket.calibrate import run_calibration

    report = await run_calibration(settings)
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run", "pair", "check-session", "calibrate"]
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if args.command == "pair" and not settings.mock_cardmarket:
        settings = settings.model_copy(update={"headless": False})
    commands = {"run": _run, "pair": _pair, "check-session": _check, "calibrate": _calibrate}
    sys.exit(asyncio.run(commands[args.command](settings)))


if __name__ == "__main__":
    main()
