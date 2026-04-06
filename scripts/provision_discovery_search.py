#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from typing import Any

import requests


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision Discovery Engine search datastore + engine and wire serving config secret."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--datastore-id", default="supplynerva-store")
    parser.add_argument("--engine-id", default="supplynerva-enterprise")
    parser.add_argument("--datastore-display-name", default="SupplyNerva Store")
    parser.add_argument("--engine-display-name", default="SupplyNerva Enterprise Search")
    parser.add_argument("--secret-name", default="aetherchain-vertex-search-serving-config")
    parser.add_argument("--gcloud-bin", default="./google-cloud-sdk/bin/gcloud")
    parser.add_argument("--seed-sample-docs", action="store_true")
    parser.add_argument(
        "--search-tier",
        default="SEARCH_TIER_ENTERPRISE",
        choices=["SEARCH_TIER_STANDARD", "SEARCH_TIER_ENTERPRISE"],
        help="Discovery engine search tier. Defaults to enterprise for GenAI-credit-heavy usage.",
    )
    parser.add_argument(
        "--enable-llm-addon",
        dest="enable_llm_addon",
        action="store_true",
        default=True,
        help="Enable Discovery Search LLM add-on (required for Answer API).",
    )
    parser.add_argument(
        "--disable-llm-addon",
        dest="enable_llm_addon",
        action="store_false",
        help="Disable Discovery Search LLM add-on.",
    )
    return parser.parse_args()


class DiscoveryProvisioner:
    def __init__(self, project_id: str, gcloud_bin: str):
        self.project_id = project_id
        self.gcloud_bin = gcloud_bin
        self.project_number = run(
            [self.gcloud_bin, "projects", "describe", project_id, "--format=value(projectNumber)"]
        )
        self.collection_parent = (
            f"projects/{self.project_number}/locations/global/collections/default_collection"
        )

    def auth_headers(self) -> dict[str, str]:
        token = run([self.gcloud_bin, "auth", "print-access-token"])
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
        url = f"https://discoveryengine.googleapis.com/v1/{path}"
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
            if response.status_code == 409:
                return body
            raise RuntimeError(f"Discovery API {method} {url} failed ({response.status_code}): {body}")
        return body

    def list_datastores(self) -> list[dict[str, Any]]:
        body = self._request("GET", f"{self.collection_parent}/dataStores")
        return body.get("dataStores", []) if isinstance(body, dict) else []

    def list_engines(self) -> list[dict[str, Any]]:
        body = self._request("GET", f"{self.collection_parent}/engines")
        return body.get("engines", []) if isinstance(body, dict) else []

    def create_datastore_if_needed(self, datastore_id: str, display_name: str) -> None:
        full_name = f"{self.collection_parent}/dataStores/{datastore_id}"
        existing = {item.get("name") for item in self.list_datastores()}
        if full_name in existing:
            print(f"Datastore exists: {full_name}")
            return

        print(f"Creating datastore: {datastore_id}")
        body = {
            "displayName": display_name,
            "industryVertical": "GENERIC",
            "solutionTypes": ["SOLUTION_TYPE_SEARCH"],
            "contentConfig": "CONTENT_REQUIRED",
        }
        result = self._request(
            "POST",
            f"{self.collection_parent}/dataStores?dataStoreId={datastore_id}",
            body,
        )
        self._wait_if_operation(result)

    @staticmethod
    def _desired_search_engine_config(search_tier: str, enable_llm_addon: bool) -> dict[str, Any]:
        config: dict[str, Any] = {"searchTier": search_tier}
        if enable_llm_addon:
            config["searchAddOns"] = ["SEARCH_ADD_ON_LLM"]
        return config

    def create_engine_if_needed(
        self,
        engine_id: str,
        display_name: str,
        datastore_id: str,
        search_tier: str,
        enable_llm_addon: bool,
    ) -> None:
        full_name = f"{self.collection_parent}/engines/{engine_id}"
        existing = {item.get("name") for item in self.list_engines()}
        if full_name in existing:
            print(f"Engine exists: {full_name}")
            return

        print(f"Creating engine: {engine_id}")
        body = {
            "displayName": display_name,
            "industryVertical": "GENERIC",
            "solutionType": "SOLUTION_TYPE_SEARCH",
            "searchEngineConfig": self._desired_search_engine_config(search_tier, enable_llm_addon),
            "dataStoreIds": [datastore_id],
        }
        result = self._request(
            "POST",
            f"{self.collection_parent}/engines?engineId={engine_id}",
            body,
        )
        self._wait_if_operation(result)

    def ensure_engine_search_config(
        self,
        engine_id: str,
        search_tier: str,
        enable_llm_addon: bool,
    ) -> None:
        engine_name = f"{self.collection_parent}/engines/{engine_id}"
        current = self._request("GET", engine_name)
        current_cfg = current.get("searchEngineConfig") or {}
        desired_cfg = self._desired_search_engine_config(search_tier, enable_llm_addon)

        current_addons = sorted(current_cfg.get("searchAddOns") or [])
        desired_addons = sorted(desired_cfg.get("searchAddOns") or [])
        if current_cfg.get("searchTier") == desired_cfg.get("searchTier") and current_addons == desired_addons:
            print(
                f"Engine search config already set: tier={desired_cfg.get('searchTier')}, "
                f"addons={desired_addons or ['<none>']}"
            )
            return

        print(
            f"Patching engine search config to tier={desired_cfg.get('searchTier')} "
            f"addons={desired_addons or ['<none>']}"
        )
        body = {
            "name": engine_name,
            "searchEngineConfig": desired_cfg,
        }
        self._request(
            "PATCH",
            f"{engine_name}?updateMask=searchEngineConfig.searchTier,searchEngineConfig.searchAddOns",
            body,
        )

    def engine_serving_config(self, engine_id: str) -> str:
        body = self._request("GET", f"{self.collection_parent}/engines/{engine_id}/servingConfigs")
        configs = body.get("servingConfigs", [])
        if not configs:
            raise RuntimeError("No servingConfigs found for engine.")

        for item in configs:
            name = str(item.get("name", ""))
            if name.endswith("/default_search"):
                return name
        return str(configs[0].get("name", ""))

    def upsert_secret(self, secret_name: str, value: str) -> None:
        try:
            run([self.gcloud_bin, "secrets", "describe", secret_name, "--project", self.project_id])
            print(f"Secret exists: {secret_name}")
        except subprocess.CalledProcessError:
            print(f"Creating secret: {secret_name}")
            run(
                [
                    self.gcloud_bin,
                    "secrets",
                    "create",
                    secret_name,
                    "--project",
                    self.project_id,
                    "--replication-policy=automatic",
                ]
            )

        add = subprocess.run(
            [
                self.gcloud_bin,
                "secrets",
                "versions",
                "add",
                secret_name,
                "--project",
                self.project_id,
                "--data-file=-",
            ],
            input=value,
            text=True,
            capture_output=True,
            check=True,
        )
        print(add.stdout.strip() or f"Updated secret {secret_name} with a new version.")

    def seed_sample_docs(self, datastore_id: str) -> None:
        docs = [
            (
                "port-la-congestion-playbook",
                "LA Port Congestion Response Playbook",
                "When Port of Los Angeles congestion exceeds 36 hours, reroute urgent containers to Port of Seattle and Port of Oakland. Reserve rail slots 48 hours in advance and pre-clear customs paperwork for SKUs SHOE-ABC and BOOT-XYZ.",
            ),
            (
                "supplier-vietnam-risk",
                "Vietnam Supplier Disruption Mitigation",
                "If Vietnam Footwear Co. misses confirmed production window by more than 2 days, activate alternate supplier in Indonesia. Prioritize high-margin SKUs and split orders into 60/40 across two routes to reduce single-point risk.",
            ),
            (
                "weather-route-impact",
                "Pacific Weather Route Delay Guidance",
                "For severe Pacific storm alerts, adjust ETA buffers by 4 to 7 days, move premium inventory to expedited air for top 10 SKUs, and notify downstream distribution centers with revised ASN schedules.",
            ),
        ]
        parent = f"{self.collection_parent}/dataStores/{datastore_id}/branches/default_branch"

        for doc_id, title, text in docs:
            body = {
                "structData": {
                    "title": title,
                    "source": "supplynerva_ops_guide",
                    "category": "supply-risk-playbook",
                },
                "content": {
                    "mimeType": "text/plain",
                    "rawBytes": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                },
            }
            result = self._request(
                "POST",
                f"{parent}/documents?documentId={doc_id}",
                body,
            )
            if result.get("error", {}).get("status") == "ALREADY_EXISTS":
                print(f"Document exists: {doc_id}")
            else:
                print(f"Created document: {doc_id}")

    def _wait_if_operation(self, result: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            return
        op_name = str(result.get("name", ""))
        done = bool(result.get("done"))
        if not op_name or done:
            return

        print(f"Waiting for operation: {op_name}")
        for _ in range(90):
            time.sleep(2)
            op = self._request("GET", op_name)
            if op.get("done"):
                if "error" in op:
                    raise RuntimeError(f"Operation failed: {op}")
                return
        raise RuntimeError(f"Timed out waiting for operation: {op_name}")


def main() -> int:
    args = parse_args()

    provisioner = DiscoveryProvisioner(
        project_id=args.project_id,
        gcloud_bin=args.gcloud_bin,
    )

    print(f"Project: {args.project_id} ({provisioner.project_number})")
    provisioner.create_datastore_if_needed(args.datastore_id, args.datastore_display_name)
    provisioner.create_engine_if_needed(
        args.engine_id,
        args.engine_display_name,
        args.datastore_id,
        args.search_tier,
        args.enable_llm_addon,
    )
    provisioner.ensure_engine_search_config(
        args.engine_id,
        args.search_tier,
        args.enable_llm_addon,
    )

    if args.seed_sample_docs:
        provisioner.seed_sample_docs(args.datastore_id)

    serving_config = provisioner.engine_serving_config(args.engine_id)
    print(f"Serving config: {serving_config}")
    provisioner.upsert_secret(args.secret_name, serving_config)

    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
