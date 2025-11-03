from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api/"


@dataclass(slots=True)
class SlackSyncStats:
    processed_messages: int
    created_issues: int
    last_timestamp: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "processed_messages": self.processed_messages,
            "created_issues": self.created_issues,
            "last_timestamp": self.last_timestamp,
        }


def _slack_request(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = urllib.parse.urljoin(SLACK_API_BASE, method)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API error ({method}): {payload}")
    return payload


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_ts": "0"}
    logger.debug("Loading Slack cursor from %s", path)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.debug("Saved Slack cursor to %s: %s", path, state)


def _fetch_new_messages(token: str, channel: str, oldest: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"channel": channel, "oldest": oldest, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        payload = _slack_request(token, "conversations.history", params)
        messages.extend(payload.get("messages", []))
        cursor = payload.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    messages.sort(key=lambda item: float(item.get("ts", "0")))
    return [m for m in messages if float(m.get("ts", "0")) > float(oldest)]


def _format_issue(message: dict[str, Any], channel: str) -> tuple[str, str]:
    text = message.get("text", "").strip()
    user = message.get("user", "unknown")
    ts = message.get("ts", "0")
    ts_float = float(ts)
    human_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_float))
    link = f"https://slack.com/app_redirect?channel={channel}&message_ts={ts}"
    title = text.splitlines()[0][:80] or "Slack Codex Request"
    body = (
        "### Slackリクエスト\n"
        f"- 投稿者: `{user}`\n"
        f"- 投稿日時 (UTC): {human_time}\n"
        f"- メッセージリンク: {link}\n\n"
        f"````\n{text}\n````\n"
    )
    return title, body


def _create_issue(repo: str, token: str, title: str, body: str, labels: list[str]) -> None:
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = json.dumps({"title": title, "body": body, "labels": labels}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        if resp.status >= 300:
            detail = resp.read().decode("utf-8")
            raise RuntimeError(f"GitHub issue creation failed: {detail}")


def run_sync(settings: Settings) -> SlackSyncStats:
    state = _load_state(settings.state_file)
    oldest = state.get("last_ts", "0")

    messages = _fetch_new_messages(settings.slack_bot_token, settings.slack_channel_id, oldest)
    processed_ts = float(oldest)
    created = 0

    for message in messages:
        if message.get("subtype"):
            continue
        text = message.get("text", "").strip()
        if not text.startswith("/codex"):
            continue
        title, body = _format_issue(message, settings.slack_channel_id)
        _create_issue(settings.github_repo, settings.github_token, title, body, ["codex-runner", "from-slack"])
        created += 1
        processed_ts = max(processed_ts, float(message.get("ts", processed_ts)))

    if created:
        _save_state(settings.state_file, {"last_ts": f"{processed_ts:.6f}"})

    logger.info("Slack sync: processed=%s created=%s last_ts=%.6f", len(messages), created, processed_ts)
    return SlackSyncStats(processed_messages=len(messages), created_issues=created, last_timestamp=processed_ts)
