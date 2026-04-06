#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

import requests


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision Conversational Agents (Dialogflow CX) agent + playbook for direct GenAI traffic."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--location", default="global", help="Dialogflow location, for example global or us-central1.")
    parser.add_argument("--agent-display-name", default="SupplyNerva Playbook Agent")
    parser.add_argument("--default-language-code", default="en")
    parser.add_argument("--time-zone", default="America/New_York")
    parser.add_argument("--playbook-display-name", default="Supply Operations Copilot")
    parser.add_argument(
        "--playbook-goal",
        default="Answer supply chain operational questions with concise, practical recommendations and clear assumptions.",
    )
    parser.add_argument(
        "--playbook-guidelines",
        default=(
            "Act as an enterprise supply operations copilot. Ask one clarifying question when data is missing, "
            "then provide prioritized actions, risks, and measurable next steps. Keep answers concise and "
            "decision-oriented."
        ),
    )
    parser.add_argument("--gcloud-bin", default="./google-cloud-sdk/bin/gcloud")
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


class PlaybookProvisioner:
    def __init__(self, project_id: str, location: str, gcloud_bin: str):
        self.project_id = project_id
        self.location = location
        self.gcloud_bin = gcloud_bin
        self.api_host = "global-dialogflow.googleapis.com" if location == "global" else f"{location}-dialogflow.googleapis.com"

    def enable_api(self) -> None:
        subprocess.check_call(
            [
                self.gcloud_bin,
                "services",
                "enable",
                "dialogflow.googleapis.com",
                "--project",
                self.project_id,
                "--quiet",
            ]
        )

    def auth_headers(self) -> dict[str, str]:
        token = run([self.gcloud_bin, "auth", "print-access-token", "--project", self.project_id])
        return {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": self.project_id,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        url = f"https://{self.api_host}/v3/{path}"
        response = requests.request(
            method,
            url,
            headers=self.auth_headers(),
            data=json.dumps(payload) if payload is not None else None,
            timeout=timeout,
        )
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if response.status_code >= 300:
            raise RuntimeError(f"Dialogflow API {method} {url} failed ({response.status_code}): {body}")
        return body

    def list_agents(self) -> list[dict[str, Any]]:
        parent = f"projects/{self.project_id}/locations/{self.location}"
        body = self._request("GET", f"{parent}/agents")
        return body.get("agents", [])

    def get_or_create_agent(
        self,
        display_name: str,
        default_language_code: str,
        time_zone: str,
    ) -> dict[str, Any]:
        for agent in self.list_agents():
            if agent.get("displayName") == display_name:
                print(f"Agent exists: {agent.get('name')}")
                return agent

        parent = f"projects/{self.project_id}/locations/{self.location}"
        payload = {
            "displayName": display_name,
            "defaultLanguageCode": default_language_code,
            "timeZone": time_zone,
        }
        created = self._request("POST", f"{parent}/agents", payload)
        print(f"Created agent: {created.get('name')}")
        return created

    def list_playbooks(self, agent_name: str) -> list[dict[str, Any]]:
        body = self._request("GET", f"{agent_name}/playbooks")
        return body.get("playbooks", [])

    def get_or_create_playbook(
        self,
        agent_name: str,
        display_name: str,
        goal: str,
        guidelines: str,
    ) -> dict[str, Any]:
        existing: dict[str, Any] | None = None
        for playbook in self.list_playbooks(agent_name):
            if playbook.get("displayName") == display_name:
                existing = playbook
                break

        if existing is None:
            payload = {
                "displayName": display_name,
                "goal": goal,
                "instruction": {"guidelines": guidelines},
            }
            created = self._request("POST", f"{agent_name}/playbooks", payload)
            print(f"Created playbook: {created.get('name')}")
            return created

        print(f"Playbook exists: {existing.get('name')}")
        current_goal = existing.get("goal", "")
        current_guidelines = ((existing.get("instruction") or {}).get("guidelines") or "")
        if current_goal == goal and current_guidelines == guidelines:
            return existing

        payload = {
            "name": existing.get("name"),
            "goal": goal,
            "instruction": {"guidelines": guidelines},
        }
        updated = self._request(
            "PATCH",
            f"{existing.get('name')}?updateMask=goal,instruction",
            payload,
        )
        print(f"Updated playbook goal/instruction: {updated.get('name')}")
        return updated


def main() -> int:
    args = parse_args()

    provisioner = PlaybookProvisioner(
        project_id=args.project_id,
        location=args.location,
        gcloud_bin=args.gcloud_bin,
    )
    provisioner.enable_api()

    agent = provisioner.get_or_create_agent(
        display_name=args.agent_display_name,
        default_language_code=args.default_language_code,
        time_zone=args.time_zone,
    )
    playbook = provisioner.get_or_create_playbook(
        agent_name=str(agent["name"]),
        display_name=args.playbook_display_name,
        goal=args.playbook_goal,
        guidelines=args.playbook_guidelines,
    )

    output = {
        "project_id": args.project_id,
        "location": args.location,
        "agent_name": agent.get("name"),
        "agent_display_name": agent.get("displayName"),
        "playbook_name": playbook.get("name"),
        "playbook_display_name": playbook.get("displayName"),
        "api_host": provisioner.api_host,
    }
    print(json.dumps(output, indent=2))

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2)
        print(f"Wrote {args.output_json}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
