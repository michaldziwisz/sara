from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from .diagnostics import collect_diagnostics
from .logs import prepare_log_file

ReportKind = Literal["bug", "suggestion"]


@dataclass(frozen=True)
class ReportError(RuntimeError):
    status: int
    payload: Any | None = None


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout_s: float) -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        method="POST",
        data=data,
        headers={
            "content-type": "application/json; charset=utf-8",
            "accept": "application/json",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            parsed = raw or None
        raise ReportError(status=e.code, payload=parsed) from e


def send_report(
    *,
    base_url: str,
    app_id: str,
    kind: ReportKind,
    title: str,
    description: str,
    app_version: str | None = None,
    app_build: str | None = None,
    app_channel: str | None = None,
    email: str | None = None,
    log_path: str | None = None,
    app_token: str | None = None,
    diagnostics_extra: dict[str, Any] | None = None,
    timeout_s: float = 12.0,
    max_log_full_bytes: int = 20_000_000,
    max_log_tail_bytes: int = 5_000_000,
    max_log_base64_length: int = 8_000_000,
) -> Any:
    base_url = base_url.rstrip("/")
    url = f"{base_url}/v1/report"

    prepared_log = (
        prepare_log_file(
            log_path or "",
            max_full_bytes=max_log_full_bytes,
            max_tail_bytes=max_log_tail_bytes,
            max_gz_base64_length=max_log_base64_length,
        )
        if log_path
        else None
    )

    body: dict[str, Any] = {
        "app": {
            "id": app_id,
            **({"version": app_version} if app_version else {}),
            **({"build": app_build} if app_build else {}),
            **({"channel": app_channel} if app_channel else {}),
        },
        "kind": kind,
        "title": title,
        "description": description,
        "diagnostics": collect_diagnostics(extra=diagnostics_extra),
        **({"email": email} if email else {}),
        **(
            {
                "logs": {
                    "fileName": prepared_log.file_name,
                    "contentType": "application/gzip",
                    "encoding": "base64",
                    "dataBase64": prepared_log.gz_base64,
                    "originalBytes": prepared_log.original_bytes,
                    "truncated": prepared_log.truncated,
                }
            }
            if prepared_log
            else {}
        ),
    }

    headers: dict[str, str] = {}
    if app_token:
        headers["x-sygnalista-app-token"] = app_token

    return _post_json(url=url, body=body, headers=headers, timeout_s=timeout_s)

