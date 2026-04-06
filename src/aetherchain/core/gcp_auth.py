from __future__ import annotations

import logging
import os
import shutil
import subprocess

from django.conf import settings
from google.auth import default as gcp_auth_default
from google.auth.transport.requests import Request as gcp_auth_request

logger = logging.getLogger(__name__)


def quota_project_id() -> str:
    configured = str(getattr(settings, "GCP_QUOTA_PROJECT_ID", "")).strip()
    if configured:
        return configured
    project_from_settings = str(getattr(settings, "GCP_PROJECT_ID", "")).strip()
    if project_from_settings:
        return project_from_settings
    return _read_gcloud_config("project")


def resolve_gcp_project_id() -> str:
    project_from_settings = str(getattr(settings, "GCP_PROJECT_ID", "")).strip()
    if project_from_settings:
        return project_from_settings

    project_from_gcloud = _read_gcloud_config("project")
    if project_from_gcloud:
        return project_from_gcloud

    try:
        _, discovered_project = gcp_auth_default()
        return str(discovered_project or "").strip()
    except Exception:
        return ""


def build_google_auth_headers(for_quota_project: str = "") -> dict[str, str]:
    token = access_token()
    headers = {"Authorization": f"Bearer {token}"}

    quota_project = str(for_quota_project or "").strip() or quota_project_id()
    if quota_project:
        headers["x-goog-user-project"] = quota_project
    return headers


def access_token() -> str:
    adc_token = _access_token_from_adc()
    if adc_token:
        return adc_token

    gcloud_token = _access_token_from_gcloud()
    if gcloud_token:
        return gcloud_token

    raise RuntimeError(
        "Unable to acquire Google access token from ADC or gcloud. "
        "Run `gcloud auth login` and `gcloud auth application-default login`."
    )


def _access_token_from_adc() -> str:
    try:
        quota_project = quota_project_id() or None
        credentials, _ = gcp_auth_default(quota_project_id=quota_project)
        if not credentials.valid or not credentials.token:
            credentials.refresh(gcp_auth_request())
        return str(credentials.token or "").strip()
    except Exception as exc:
        logger.info("ADC token unavailable, falling back to gcloud token: %s", exc)
        return ""


def _access_token_from_gcloud() -> str:
    gcloud_bin = _resolve_gcloud_bin()
    try:
        completed = subprocess.run(
            [gcloud_bin, "auth", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return completed.stdout.strip()
    except Exception as exc:
        logger.warning("gcloud access-token fallback failed: %s", exc)
        return ""


def _read_gcloud_config(key: str) -> str:
    gcloud_bin = _resolve_gcloud_bin()
    try:
        completed = subprocess.run(
            [gcloud_bin, "config", "get-value", key],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = completed.stdout.strip()
        return "" if value == "(unset)" else value
    except Exception:
        return ""


def _resolve_gcloud_bin() -> str:
    configured = str(getattr(settings, "GCLOUD_BIN", "")).strip()
    if configured and configured != "gcloud":
        return configured

    system_gcloud = shutil.which("gcloud")
    if system_gcloud:
        return system_gcloud

    local_candidates = [
        "/Users/ritwij/google-cloud-sdk/bin/gcloud",
        "/Users/ritwij/Documents/aetherchain-project/google-cloud-sdk/bin/gcloud",
    ]
    for candidate in local_candidates:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return "gcloud"
