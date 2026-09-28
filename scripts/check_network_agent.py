"""Explicit, small live test. Never runs as part of pytest. Two model calls."""

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values

from adapters.network.agent import AgentRequest, ClaudeProvider, NetworkAgent
from adapters.network.scenario import load_scenario


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("tmp/network-agent-live.json"))
    args = parser.parse_args()
    provider = ClaudeProvider(dotenv_values(args.env_file))
    try:
        result = NetworkAgent(provider, max_requests=1).answer(
            load_scenario(),
            AgentRequest(
                question="我想做 Cybertest，用 AI agent 做授权的对抗性安全测试，改善 vibe coding 的安全性。我应该先找谁、network 里还缺哪些能力、怎么扩大关系？"
            ),
            1,
        )
    except Exception as error:  # noqa: BLE001 - never print raw provider request details
        reason = (
            str(error)
            if type(error) is ValueError
            else "Provider or schema error (details withheld)"
        )
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "reason": reason}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "model": result["model"],
                "usage": result["usage"],
                "findings": len(result["findings"]),
                "sources": len(result["evidence"]),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
