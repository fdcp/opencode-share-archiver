#!/usr/bin/env python3

"""OpenCode-backed visual subagent.

Default provider/model: github-copilot/gpt-4o
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = os.environ.get("LOOK_AT_MODEL", "github-copilot/gpt-4o")
DEFAULT_AGENT = os.environ.get("LOOK_AT_AGENT", "default")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "opencode")


@dataclass
class LookAtResult:
    image: str
    goal: str
    model: str
    agent: str
    summary: str
    verdict: str


def parse_args():
    p = argparse.ArgumentParser(description="OpenCode-backed visual subagent")
    p.add_argument("image", nargs="?", help="Path to screenshot image")
    p.add_argument("goal", nargs="?", help="Inspection goal text")
    p.add_argument("--image", dest="image_opt", help="Path to screenshot image")
    p.add_argument("--goal", dest="goal_opt", help="Inspection goal text")
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenCode model, default github-copilot/gpt-4o")
    p.add_argument("--agent", default=DEFAULT_AGENT, help="OpenCode agent name (default: default)")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p.parse_args()


def resolve_inputs(args):
    image = args.image_opt or args.image
    goal = args.goal_opt or args.goal
    if not image or not goal:
        raise SystemExit("Error: image and goal are required")
    return image, goal


def build_prompt(image: str, goal: str) -> str:
    section = Path(image).stem.replace("new_", "").replace("old_", "")
    return (
        "You are a visual QA subagent for HTML screenshots. "
        "Inspect the provided screenshot and answer in concise Chinese. "
        "Return a Markdown '检测结果分析表' and then a final verdict line.\n\n"
        f"当前区域: {section}\n"
        f"Image path: {image}\n"
        f"Expected behavior: {goal}\n\n"
        "Output format:\n"
        "# 检测结果分析表\n"
        "| 检查项 | 当前观察 | 预期 | 结论 |\n"
        "|---|---|---|---|\n"
        "| ... | ... | ... | pass/fail/info |\n\n"
        "最终结论: pass|fail|info\n"
        "备注: optional short note"
    )


def extract_verdict(text: str) -> str:
    match = re.search(r"(?im)^(?:最终结论|verdict)[:：]\s*(pass|fail|info)\s*$", text)
    if match:
        return match.group(1)
    return "info"


def call_opencode(image: str, goal: str, model: str, agent: str) -> LookAtResult:
    prompt = build_prompt(image, goal)
    cmd = [
        OPENCODE_BIN,
        "run",
        prompt,
        "--model",
        model,
        "--agent",
        agent,
        "--format",
        "json",
        "--file",
        image,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"opencode exited with {proc.returncode}")

    report_text = ""
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get("type") == "text":
            report_text = event.get("part", {}).get("text", report_text)

    if not report_text.strip():
        report_text = proc.stdout.strip() or "No summary returned"

    parsed_verdict = extract_verdict(report_text)

    return LookAtResult(
        image=image,
        goal=goal,
        model=model,
        agent=agent,
        summary=report_text,
        verdict=parsed_verdict,
    )


def main():
    args = parse_args()
    image, goal = resolve_inputs(args)
    result = call_opencode(image, goal, args.model, args.agent)
    if args.json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(result.summary)


if __name__ == "__main__":
    main()
