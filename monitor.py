#!/usr/bin/env python3
"""Read-only public Telegram monitor for 52pokemon coupon clues.

The default path uses only Telegram's anonymous public web preview.  It never
logs in, joins a group, calls the Telegram API, or touches the target website.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from discussion import (
    collect_public_discussion,
    extract_comment_consensus,
    load_pokemon_names,
)

USER_AGENT = "pokemon521-coupon-monitor/0.2 (+https://github.com/)"
ACTIVITY_TERMS = (
    "兑换码",
    "优惠码",
    "优惠口令",
    "白嫖",
    "入门精灵球",
    "免费流量",
    "限定流量",
    "猜出",
    "猜码",
)
CODE_STOPWORDS = {
    "藏在图片",
    "藏在一张",
    "查看活动图片",
    "填写优惠码",
    "购买入门精灵球",
    "不要在兑换码处兑换",
}
CODE_PATTERN = re.compile(
    r"(?:兑换码|优惠码|优惠口令|白嫖(?:兑换)?码|激活码|"
    r"coupon(?:\s*code)?|promo(?:\s*code)?|code)"
    r"\s*(?:是|为|叫|[:：=])\s*"
    r"([A-Za-z0-9\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_-]{1,31})",
    re.IGNORECASE,
)
BACKGROUND_URL_PATTERN = re.compile(
    r"background-image\s*:\s*url\(\s*['\"]?([^'\")]+)", re.IGNORECASE
)
TRAILING_PUNCTUATION = "\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff09\u3011\u300b\u201d\u2019,.;:!?)]}"


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    status: int
    final_url: str
    content_type: str
    body: str


@dataclass(frozen=True)
class TelegramMessage:
    post_path: str
    post_id: int
    source_url: str
    published_at: str | None
    text: str
    media_urls: tuple[str, ...]
    reply_url: str | None
    reply_count: int | None
    views: str | None

    def to_dict(self) -> dict:
        return {
            "post_path": self.post_path,
            "post_id": self.post_id,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "text": self.text,
            "media_urls": list(self.media_urls),
            "reply_url": self.reply_url,
            "reply_count": self.reply_count,
            "views": self.views,
        }


class PublicHistoryParser(HTMLParser):
    """Parse Telegram's public /s/<channel> HTML without third-party packages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[TelegramMessage] = []
        self.div_depth = 0
        self.wrapper_depth: int | None = None
        self.current: dict | None = None
        self.text_depth: int | None = None
        self.text_parts: list[str] = []
        self.reply_depth: int | None = None
        self.reply_parts: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    @staticmethod
    def _classes(attrs: dict[str, str]) -> set[str]:
        return set(attrs.get("class", "").split())

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = self._attrs(attrs_list)
        classes = self._classes(attrs)

        if tag == "div":
            new_depth = self.div_depth + 1
            if self.current is None and (
                "tgme_widget_message_wrap" in classes or "tgme_widget_message" in classes
            ):
                post_path = attrs.get("data-post", "").strip()
                if post_path:
                    self.current = {
                        "post_path": post_path,
                        "published_at": None,
                        "media_urls": [],
                        "reply_url": None,
                        "reply_count": None,
                        "views": None,
                    }
                    self.wrapper_depth = new_depth
            self.div_depth = new_depth

            if self.current is not None and "tgme_widget_message_text" in classes:
                self.text_depth = self.div_depth
                self.text_parts = []
            if self.current is not None and "tgme_widget_message_replies" in classes:
                self.reply_depth = self.div_depth
                self.reply_parts = []
                if attrs.get("href"):
                    self.current["reply_url"] = attrs["href"]
            return

        if self.current is None:
            return

        if tag == "br" and self.text_depth is not None:
            self.text_parts.append("\n")
        elif tag == "time" and attrs.get("datetime"):
            self.current["published_at"] = attrs["datetime"]
        elif tag == "a" and self.reply_depth is not None and attrs.get("href"):
            self.current["reply_url"] = attrs["href"]
        elif tag == "a" and "tgme_widget_message_photo_wrap" in classes:
            style = attrs.get("style", "")
            match = BACKGROUND_URL_PATTERN.search(style)
            if match:
                url = match.group(1)
                if url not in self.current["media_urls"]:
                    self.current["media_urls"].append(url)
        elif tag in {"video", "source"}:
            for key in ("poster", "src"):
                if attrs.get(key) and attrs[key] not in self.current["media_urls"]:
                    self.current["media_urls"].append(attrs[key])

        if "tgme_widget_message_views" in classes:
            self.current["views_depth"] = self.div_depth
            self.current["views_parts"] = []

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        if self.text_depth is not None:
            self.text_parts.append(data)
        if self.reply_depth is not None:
            self.reply_parts.append(data)
        if "views_depth" in self.current:
            self.current.setdefault("views_parts", []).append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return

        if self.current is not None:
            if self.text_depth == self.div_depth:
                self.text_depth = None
            if self.reply_depth == self.div_depth:
                raw = "".join(self.reply_parts)
                match = re.search(r"(\d+)", raw)
                self.current["reply_count"] = int(match.group(1)) if match else None
                self.reply_depth = None
            if self.current.get("views_depth") == self.div_depth:
                raw = "".join(self.current.pop("views_parts", []))
                self.current["views"] = raw.strip() or None
                self.current.pop("views_depth", None)

            if self.wrapper_depth == self.div_depth:
                self._finish_current()
                self.wrapper_depth = None

        self.div_depth = max(0, self.div_depth - 1)

    def _finish_current(self) -> None:
        assert self.current is not None
        post_path = self.current["post_path"]
        match = re.search(r"/(\d+)$", post_path)
        if not match:
            self.current = None
            return
        text = clean_text("".join(self.text_parts))
        self.messages.append(
            TelegramMessage(
                post_path=post_path,
                post_id=int(match.group(1)),
                source_url=f"https://t.me/{post_path}",
                published_at=self.current.get("published_at"),
                text=text,
                media_urls=tuple(self.current.get("media_urls", [])),
                reply_url=self.current.get("reply_url"),
                reply_count=self.current.get("reply_count"),
                views=self.current.get("views"),
            )
        )
        self.current = None
        self.text_depth = None
        self.reply_depth = None
        self.text_parts = []
        self.reply_parts = []


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_code(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", "", value)
    return value.strip(TRAILING_PUNCTUATION).casefold()


def plausible_code(value: str) -> bool:
    value = value.strip(TRAILING_PUNCTUATION).strip()
    if not 2 <= len(value) <= 32:
        return False
    normalized = normalize_code(value)
    if not normalized or normalized in {normalize_code(x) for x in CODE_STOPWORDS}:
        return False
    if "http" in normalized or "t.me" in normalized:
        return False
    return any(ch.isalpha() or "\u3400" <= ch <= "\u9fff" for ch in value)


def excerpt(text: str, limit: int = 240) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def extract_signals(message: TelegramMessage) -> list[dict]:
    """Extract only high-confidence text codes and image clues.

    A media clue is deliberately not decoded.  It is surfaced for manual review.
    """
    signals: list[dict] = []
    text = message.text
    activity = any(term in text for term in ACTIVITY_TERMS)

    for match in CODE_PATTERN.finditer(text):
        code = match.group(1).strip(TRAILING_PUNCTUATION)
        if not plausible_code(code):
            continue
        signals.append(
            {
                "kind": "text_code",
                "code": code,
                "code_normalized": normalize_code(code),
                "extraction_method": "label_regex_v1",
                "post_id": message.post_id,
                "source_url": message.source_url,
                "published_at": message.published_at,
                "evidence": excerpt(text),
                "media_urls": list(message.media_urls),
                "needs_manual_review": False,
            }
        )

    if not signals and activity and message.media_urls:
        signals.append(
            {
                "kind": "media_clue",
                "extraction_method": "media_presence_rule_v1",
                "post_id": message.post_id,
                "source_url": message.source_url,
                "published_at": message.published_at,
                "evidence": excerpt(text),
                "media_urls": list(message.media_urls),
                "needs_manual_review": True,
                "reason": "活动文字存在，但兑换码可能只写在图片中；未进行 OCR 或猜码。",
            }
        )
    return signals


def fetch_url(url: str, timeout: int = 30) -> FetchResult:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return FetchResult(
                requested_url=url,
                status=int(response.status),
                final_url=response.geturl(),
                content_type=response.headers.get("content-type", ""),
                body=body,
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return FetchResult(
            requested_url=url,
            status=int(exc.code),
            final_url=exc.geturl(),
            content_type=exc.headers.get("content-type", "") if exc.headers else "",
            body=body,
        )
    except URLError as exc:
        raise RuntimeError(f"GET failed for {url}: {exc.reason}") from exc


def parse_public_history(body: str) -> list[TelegramMessage]:
    parser = PublicHistoryParser()
    parser.feed(body)
    parser.close()
    unique: dict[int, TelegramMessage] = {}
    for message in parser.messages:
        unique[message.post_id] = message
    return sorted(unique.values(), key=lambda item: item.post_id)


def before_url(history_url: str, post_id: int) -> str:
    parts = urlsplit(history_url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "before"]
    query.append(("before", str(post_id)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def collect_public_channel(
    history_url: str,
    max_messages: int = 100,
    max_pages: int = 8,
    fetcher: Callable[[str], FetchResult] = fetch_url,
) -> tuple[list[TelegramMessage], int, list[str]]:
    messages: dict[int, TelegramMessage] = {}
    next_url = history_url
    visited_urls: list[str] = []
    previous_oldest: int | None = None

    for _ in range(max_pages):
        response = fetcher(next_url)
        visited_urls.append(next_url)
        if response.status != 200:
            raise RuntimeError(f"public Telegram page returned HTTP {response.status}: {next_url}")
        page_messages = parse_public_history(response.body)
        if not page_messages:
            break
        for message in page_messages:
            messages[message.post_id] = message
        if len(messages) >= max_messages:
            break
        oldest = min(message.post_id for message in page_messages)
        if previous_oldest == oldest or oldest <= 1:
            break
        previous_oldest = oldest
        next_url = before_url(history_url, oldest)

    ordered = sorted(messages.values(), key=lambda item: (item.published_at or "", item.post_id), reverse=True)
    return ordered[:max_messages], len(visited_urls), visited_urls


def probe_group_public_preview(
    username: str,
    profile_url: str,
    history_url: str,
    fetcher: Callable[[str], FetchResult] = fetch_url,
) -> dict:
    attempts: list[dict] = []
    for url in (history_url, profile_url):
        response = fetcher(url)
        message_count = len(parse_public_history(response.body)) if response.status == 200 else 0
        attempts.append(
            {
                "requested_url": url,
                "status": response.status,
                "resolved_url": response.final_url,
                "message_count": message_count,
                "content_type": response.content_type,
            }
        )
    has_history = any(item["message_count"] > 0 for item in attempts)
    return {
        "username": username,
        "status": "public_history" if has_history else "profile_only",
        "access": "anonymous_public_preview",
        "history_available_without_token": has_history,
        "note": (
            "公开预览未返回消息记录；完整交流群历史不在 v1 抓取范围内。"
            if not has_history
            else "公开预览返回了消息记录。"
        ),
        "attempts": attempts,
    }


def load_sources(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"source config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "channel" not in data or "group" not in data:
        raise ValueError("source config must contain channel and group")
    return data


def signal_key(signal: dict) -> tuple:
    return (
        signal.get("kind"),
        signal.get("post_id"),
        signal.get("code_normalized", ""),
    )


def append_history(path: Path, signals: Iterable[dict]) -> int:
    existing: set[tuple] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(signal_key(json.loads(line)))
            except json.JSONDecodeError:
                continue

    new_records: list[dict] = []
    detected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for signal in signals:
        key = signal_key(signal)
        if key in existing:
            continue
        record = dict(signal)
        record["detected_at"] = detected_at
        new_records.append(record)
        existing.add(key)

    if new_records:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in new_records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return len(new_records)


def stable_signal(signal: dict) -> dict:
    return {key: signal[key] for key in sorted(signal) if key not in {"detected_at"}}


def signal_freshness(signal: dict) -> str:
    value = signal.get("published_at")
    if not value:
        return "unknown"
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    now = datetime.now(timezone.utc)
    if (published.year, published.month) == (now.year, now.month):
        return "current_month"
    return "historical" if published < now else "future_dated"


def signal_view(signal: dict) -> dict:
    result = stable_signal(signal)
    result["freshness"] = signal_freshness(signal)
    return result


def load_lock_state(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "lock_observations_required": 3, "months": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid lock state JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"lock state must be an object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("lock_observations_required", 3)
    payload.setdefault("months", {})
    if not isinstance(payload["months"], dict):
        raise ValueError(f"lock state months must be an object: {path}")
    return payload


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def select_run_candidate(signals: list[dict]) -> dict | None:
    grouped: dict[str, list[dict]] = {}
    for signal in signals:
        if signal.get("kind") not in {"text_code", "comment_consensus"}:
            continue
        if signal_freshness(signal) != "current_month":
            continue
        grouped.setdefault(signal.get("code_normalized", ""), []).append(signal)

    ranked: list[tuple[tuple[int, int, int], str, dict]] = []
    for code, rows in grouped.items():
        best = max(
            rows,
            key=lambda row: (
                int(row.get("distinct_author_count", 0)),
                int(row.get("matching_comment_count", 0)),
                1 if row.get("kind") == "comment_consensus" else 0,
            ),
        )
        score = (
            int(best.get("distinct_author_count", 0)),
            int(best.get("matching_comment_count", 0)),
            len(rows),
        )
        ranked.append((score, code, best))
    if not ranked:
        return None
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][2]


def update_lock_state(state: dict, signals: list[dict], required: int) -> tuple[dict, bool, dict]:
    month = current_month_key()
    months = state.setdefault("months", {})
    before = json.dumps(state, ensure_ascii=False, sort_keys=True)
    month_state = months.setdefault(
        month,
        {
            "status": "observing",
            "candidate": None,
            "observations": 0,
            "run_observations": [],
        },
    )
    month_state.setdefault("run_observations", [])
    month_state.setdefault("observations", 0)
    month_state.setdefault("status", "observing")

    if month_state.get("status") == "locked":
        return state, before != json.dumps(state, ensure_ascii=False, sort_keys=True), month_state

    selected = select_run_candidate(signals)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if selected is not None:
        candidate = selected.get("code_normalized")
        if month_state.get("candidate") == candidate:
            month_state["observations"] = int(month_state.get("observations", 0)) + 1
        else:
            month_state["candidate"] = candidate
            month_state["observations"] = 1
            month_state["run_observations"] = []
        month_state["last_observed_at"] = now
        month_state["source_post_id"] = selected.get("post_id")
        month_state["matching_comment_count"] = selected.get("matching_comment_count")
        month_state["distinct_author_count"] = selected.get("distinct_author_count")
        month_state["run_observations"].append(
            {
                "observed_at": now,
                "candidate": candidate,
                "post_id": selected.get("post_id"),
                "matching_comment_count": selected.get("matching_comment_count"),
                "distinct_author_count": selected.get("distinct_author_count"),
            }
        )
        month_state["run_observations"] = month_state["run_observations"][-required:]
        if int(month_state["observations"]) >= required:
            month_state["status"] = "locked"
            month_state["locked_at"] = month_state.get("locked_at") or now
        else:
            month_state["status"] = "observing"
    else:
        month_state["last_checked_at"] = now
        month_state["status"] = "conflict" if month_state.get("candidate") else "observing"
        # A failed or conflicting run breaks consecutive agreement. Do not
        # carry old observations into a later lock decision.
        month_state["observations"] = 0
        month_state["run_observations"] = []

    after = json.dumps(state, ensure_ascii=False, sort_keys=True)
    return state, before != after, month_state


def build_payload(
    sources: dict,
    messages: list[TelegramMessage],
    signals: list[dict],
    group_probe: dict,
    lock_state: dict,
    discussion_runs: list[dict],
) -> dict:
    text_codes: dict[str, dict] = {}
    media_clues: dict[int, dict] = {}
    for signal in signals:
        if signal["kind"] in {"text_code", "comment_consensus"}:
            key = signal["code_normalized"]
            old = text_codes.get(key)
            if old is None or (
                signal.get("published_at") or "",
                signal["post_id"],
                signal.get("matching_comment_count", 0),
            ) > (
                old.get("published_at") or "",
                old["post_id"],
                old.get("matching_comment_count", 0),
            ):
                text_codes[key] = signal
        elif signal["kind"] == "media_clue":
            old = media_clues.get(signal["post_id"])
            if old is None:
                media_clues[signal["post_id"]] = signal

    all_relevant = list(text_codes.values()) + list(media_clues.values())
    current_text_codes = {
        key: signal for key, signal in text_codes.items() if signal_freshness(signal) == "current_month"
    }
    current_media_clues = {
        key: signal for key, signal in media_clues.items() if signal_freshness(signal) == "current_month"
    }
    current_relevant = list(current_text_codes.values()) + list(current_media_clues.values())
    all_relevant.sort(key=lambda item: (item.get("published_at") or "", item["post_id"]), reverse=True)
    current_relevant.sort(key=lambda item: (item.get("published_at") or "", item["post_id"]), reverse=True)
    latest = (current_relevant or all_relevant or [None])[0]

    month_state = lock_state.get("months", {}).get(current_month_key(), {})
    locked = month_state.get("status") == "locked"
    if locked:
        status = "locked"
    elif current_text_codes:
        status = "comment_candidates" if any(
            signal.get("kind") == "comment_consensus" for signal in current_text_codes.values()
        ) else "text_candidates"
    elif current_media_clues:
        status = "media_needs_manual_review"
    elif all_relevant:
        status = "historical_only"
    else:
        status = "no_relevant_posts"

    latest_post = None
    if latest:
        latest_post = {
            "post_id": latest["post_id"],
            "source_url": latest["source_url"],
            "published_at": latest.get("published_at"),
            "freshness": signal_freshness(latest),
            "evidence": latest.get("evidence"),
            "media_urls": latest.get("media_urls", []),
            "signal_kind": latest["kind"],
        }

    candidates = [signal_view(current_text_codes[key]) for key in sorted(current_text_codes)]
    # A media clue is unresolved only when no independent public-text
    # candidate has been established for the current month.  Once the
    # discussion consensus path succeeds, do not create a fake manual-review
    # queue for the same post.
    manual_review = [] if current_text_codes else [
        signal_view(current_media_clues[key]) for key in sorted(current_media_clues, reverse=True)
    ]
    return {
        "schema_version": 2,
        "status": status,
        "source": {
            "channel": sources["channel"]["username"],
            "history_url": sources["channel"]["history_url"],
            "access": "anonymous_public_history_and_discussion_widget",
            "extraction": "rules_v2_public_discussion_consensus",
        },
        "scanned_message_count": len(messages),
        "historical_signal_count": len(all_relevant) - len(current_relevant),
        "latest_relevant_post": latest_post,
        "candidates": candidates,
        "manual_review": manual_review,
        "lock": {
            "month": current_month_key(),
            "status": month_state.get("status", "observing"),
            "candidate": month_state.get("candidate"),
            "observations": month_state.get("observations", 0),
            "required_observations": lock_state.get("lock_observations_required", 3),
            "locked_at": month_state.get("locked_at"),
        },
        "discussion_runs": discussion_runs,
        "group_probe": group_probe,
        "non_goals": [
            "no Telegram login, API credentials, cookies, or Session file",
            "no group join or comment posting",
            "no OCR or image guessing",
            "no coupon validation, order creation, or redemption",
        ],
    }


def write_json_if_changed(path: Path, payload: dict) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("sources.json"))
    parser.add_argument("--output", type=Path, default=Path("data/latest.json"))
    parser.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    parser.add_argument("--pokemon-names", type=Path, default=Path("data/pokemon_names_zh.json"))
    parser.add_argument("--max-messages", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--max-discussion-posts", type=int, default=3)
    parser.add_argument("--max-comments", type=int, default=500)
    parser.add_argument("--lock-observations", type=int, default=3)
    parser.add_argument("--ignore-lock", action="store_true")
    args = parser.parse_args(argv)

    if args.lock_observations < 2:
        raise ValueError("--lock-observations must be at least 2")
    state = load_lock_state(args.state)
    state["lock_observations_required"] = args.lock_observations
    month_state = state.get("months", {}).get(current_month_key(), {})
    if not args.ignore_lock and month_state.get("status") == "locked":
        print(json.dumps({
            "status": "locked_skip",
            "month": current_month_key(),
            "candidate": month_state.get("candidate"),
            "observations": month_state.get("observations", 0),
        }, ensure_ascii=False, sort_keys=True))
        return 0

    sources = load_sources(args.sources)
    channel = sources["channel"]
    messages, pages, visited_urls = collect_public_channel(
        channel["history_url"], max_messages=args.max_messages, max_pages=args.max_pages
    )
    signals = [signal for message in messages for signal in extract_signals(message)]

    pokemon_names = load_pokemon_names(args.pokemon_names)
    message_by_id = {message.post_id: message for message in messages}
    target_ids = []
    for signal in signals:
        if signal.get("kind") == "media_clue" and signal_freshness(signal) == "current_month":
            if signal["post_id"] not in target_ids:
                target_ids.append(signal["post_id"])
    target_ids = target_ids[: max(0, args.max_discussion_posts)]

    discussion_signals: list[dict] = []
    discussion_runs: list[dict] = []
    for post_id in target_ids:
        message = message_by_id[post_id]
        discussion = collect_public_discussion(
            channel["username"], post_id, max_comments=args.max_comments
        )
        consensus = extract_comment_consensus(
            discussion,
            post_id=post_id,
            post_url=message.source_url,
            published_at=message.published_at,
            pokemon_names=pokemon_names,
        )
        discussion_signals.extend(consensus)
        discussion_runs.append({
            "post_id": post_id,
            "source_url": message.source_url,
            "available": discussion.get("available", False),
            "error": discussion.get("error"),
            "comment_count": discussion.get("comment_count"),
            "loaded_count": discussion.get("loaded_count", 0),
            "pages": discussion.get("pages", 0),
            "truncated": discussion.get("truncated", False),
            "consensus": [
                {
                    "code": row["code"],
                    "matching_comment_count": row.get("matching_comment_count"),
                    "distinct_author_count": row.get("distinct_author_count"),
                }
                for row in consensus
            ],
        })

    all_signals = signals + discussion_signals
    group = sources["group"]
    group_probe = probe_group_public_preview(
        group["username"], group["profile_url"], group["history_url"]
    )
    state, state_changed, month_state = update_lock_state(
        state, all_signals, args.lock_observations
    )
    if state_changed:
        write_json_if_changed(args.state, state)
    new_history = append_history(args.history, all_signals)
    payload = build_payload(
        sources, messages, all_signals, group_probe, state, discussion_runs
    )
    changed = write_json_if_changed(args.output, payload)

    summary = {
        "status": payload["status"],
        "scanned_messages": len(messages),
        "pages": pages,
        "signals": len(all_signals),
        "discussion_posts": len(target_ids),
        "new_history_records": new_history,
        "state_changed": state_changed,
        "latest_json_changed": changed,
        "group_status": group_probe["status"],
        "lock_status": month_state.get("status"),
        "lock_candidate": month_state.get("candidate"),
        "lock_observations": month_state.get("observations", 0),
        "visited_pages": visited_urls,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
