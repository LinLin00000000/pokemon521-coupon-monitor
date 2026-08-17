#!/usr/bin/env python3
"""Read public Telegram channel discussions through the Discussion Widget.

This module uses only the anonymous public widget surface.  It does not use a
Telegram account, Bot Token, API ID/hash, cookie, or Session file.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "pokemon521-coupon-monitor/0.2 (+https://github.com/)"
PUNCTUATION = "\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff09\u3011\u300b\u201d\u2019,.;:!?)]}"
NON_ANSWER_TERMS = {
    "官网",
    "答案",
    "兑换",
    "兑换码",
    "优惠码",
    "流量",
    "活动",
    "成功",
    "领取",
    "谢谢",
}


@dataclass(frozen=True)
class PublicComment:
    comment_id: int
    text: str
    published_at: str | None
    author_key: str | None


class DiscussionHTMLParser(HTMLParser):
    """Parse the server-rendered Telegram discussion widget with stdlib only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.comment_depth: int | None = None
        self.text_depth: int | None = None
        self.text_parts: list[str] = []
        self.current: dict | None = None
        self.comments: list[PublicComment] = []
        self.fields: dict[str, str] = {}
        self.next_before: int | None = None
        self.next_after: int | None = None

    @staticmethod
    def attrs(attrs_list: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs_list}

    @staticmethod
    def classes(attrs: dict[str, str]) -> set[str]:
        return set(attrs.get("class", "").split())

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = self.attrs(attrs_list)
        classes = self.classes(attrs)

        if attrs.get("data-before", "").isdigit():
            self.next_before = int(attrs["data-before"])
        if attrs.get("data-after", "").isdigit():
            self.next_after = int(attrs["data-after"])

        if tag == "input" and attrs.get("name") in {"peer", "top_msg_id", "discussion_hash"}:
            self.fields[attrs["name"]] = html_module.unescape(attrs.get("value", ""))

        if tag == "div":
            self.depth += 1
            if (
                self.current is None
                and "js-widget_message" in classes
                and attrs.get("data-post-id", "").isdigit()
            ):
                self.current = {
                    "comment_id": int(attrs["data-post-id"]),
                    "text": [],
                    "published_at": None,
                    "author_href": "",
                }
                self.comment_depth = self.depth

            if self.current is not None and "tgme_widget_message_text" in classes:
                self.text_depth = self.depth
                self.text_parts = []

        if self.current is not None:
            if tag == "a" and "tgme_widget_message_author_name" in classes:
                self.current["author_href"] = attrs.get("href", "")
            elif tag == "time" and attrs.get("datetime"):
                self.current["published_at"] = attrs["datetime"]

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.text_depth is not None:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return

        if self.current is not None:
            if self.text_depth == self.depth:
                self.current["text"] = list(self.text_parts)
                self.text_depth = None
                self.text_parts = []
            if self.comment_depth == self.depth:
                raw_text = "".join(self.current.get("text", []))
                href = self.current.get("author_href", "")
                author_key = None
                if href.startswith("https://t.me/"):
                    author_key = hashlib.sha256(href.encode("utf-8")).hexdigest()[:16]
                self.comments.append(
                    PublicComment(
                        comment_id=int(self.current["comment_id"]),
                        text=clean_comment_text(raw_text),
                        published_at=self.current.get("published_at"),
                        author_key=author_key,
                    )
                )
                self.current = None
                self.comment_depth = None
                self.text_depth = None
                self.text_parts = []

        self.depth = max(0, self.depth - 1)


def clean_comment_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\xa0", " ")
    return " ".join(value.split()).strip()


def normalize_answer(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\s+", "", value)
    value = value.strip(PUNCTUATION)
    return value


def load_pokemon_names(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = payload.get("names") if isinstance(payload, dict) else payload
    if not isinstance(names, list):
        raise ValueError(f"pokemon name file has no names list: {path}")
    return {normalize_answer(str(name)) for name in names if str(name).strip()}


def extract_pokemon_candidate(text: str, names: set[str]) -> str | None:
    normalized = normalize_answer(text)
    if not normalized or normalized in NON_ANSWER_TERMS:
        return None
    if normalized in names:
        return normalized

    # Accept short natural-language wrappers such as “我猜是飞天螳螂吧”, but
    # only when exactly one known Pokémon name is present.
    matches = [name for name in names if name and name in normalized]
    # Short names can be substrings of longer canonical names (for example
    # 地鼠 -> 三地鼠). Keep a single maximal match, but still reject a
    # sentence that contains two unrelated Pokémon names.
    maximal_matches = [
        name for name in matches
        if not any(name != other and name in other for other in matches)
    ]
    if len(maximal_matches) != 1:
        return None
    candidate = maximal_matches[0]
    if candidate in NON_ANSWER_TERMS:
        return None
    remainder = normalized.replace(candidate, "", 1)
    remainder = re.sub(r"^(?:我猜|猜|答案|我觉得|应该|可能|感觉|就是|是)+", "", remainder)
    remainder = re.sub(r"(?:吧|呢|啊|呀|是|了)+$", "", remainder)
    if remainder == "":
        return candidate
    return None


def parse_discussion_html(body: str) -> dict:
    parser = DiscussionHTMLParser()
    parser.feed(body)
    parser.close()
    unique = {comment.comment_id: comment for comment in parser.comments}
    count_match = re.search(r"(\d[\d,]*)\s+comments", body, re.IGNORECASE)
    count = int(count_match.group(1).replace(",", "")) if count_match else None
    return {
        "comments": sorted(unique.values(), key=lambda item: item.comment_id),
        "comment_count": count,
        "next_before": parser.next_before,
        "next_after": parser.next_after,
        "fields": parser.fields,
    }


def _get(url: str, timeout: int = 45) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return int(exc.code), body
    except URLError as exc:
        raise RuntimeError(f"GET failed for {url}: {exc.reason}") from exc


def _post_json(url: str, data: dict[str, str], timeout: int = 45) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    request = Request(url, data=urlencode(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"POST failed for public discussion endpoint: HTTP {exc.code} {body[:160]}") from exc
    except URLError as exc:
        raise RuntimeError(f"POST failed for public discussion endpoint: {exc.reason}") from exc


def _widget_api_url(body: str) -> str | None:
    match = re.search(r"TWidgetAuth\.init\((\{.*?\})\);", body, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1).replace("\\/", "/"))
    except json.JSONDecodeError:
        return None
    api_url = payload.get("api_url")
    return api_url if isinstance(api_url, str) else None


def collect_public_discussion(
    channel: str,
    post_id: int,
    *,
    max_comments: int = 500,
    max_pages: int = 20,
    sleep_seconds: float = 0.25,
) -> dict:
    """Fetch a bounded public discussion, including older widget pages."""
    page_url = f"https://t.me/{channel}/{post_id}?embed=1&discussion=1&comments_limit=50"
    status, body = _get(page_url)
    if status != 200:
        return {
            "available": False,
            "error": f"discussion widget returned HTTP {status}",
            "source_url": page_url,
            "comments": [],
            "comment_count": None,
            "loaded_count": 0,
            "pages": 0,
        }

    first = parse_discussion_html(body)
    comments: dict[int, PublicComment] = {item.comment_id: item for item in first["comments"]}
    comment_count = first.get("comment_count")
    api_url = _widget_api_url(body)
    fields = first.get("fields", {})
    next_before = first.get("next_before")
    pages = 1
    error = None

    while next_before is not None and len(comments) < max_comments and pages < max_pages:
        if not api_url or not all(fields.get(key) for key in ("peer", "top_msg_id", "discussion_hash")):
            error = "discussion widget pagination metadata is incomplete"
            break
        try:
            payload = _post_json(
                api_url,
                {
                    "method": "loadComments",
                    "peer": fields["peer"],
                    "top_msg_id": fields["top_msg_id"],
                    "discussion_hash": fields["discussion_hash"],
                    "before_id": str(next_before),
                },
            )
        except RuntimeError as exc:
            error = str(exc)
            break
        if not payload.get("ok"):
            error = str(payload.get("error") or "loadComments returned ok=false")
            break

        fragment = payload.get("comments_html") or ""
        page = parse_discussion_html(fragment)
        for item in page["comments"]:
            comments[item.comment_id] = item
        if isinstance(payload.get("comments_cnt"), int):
            comment_count = payload["comments_cnt"]
        new_before = page.get("next_before")
        pages += 1
        if new_before is None or new_before == next_before:
            next_before = None
        else:
            next_before = new_before
        if sleep_seconds > 0 and next_before is not None:
            time.sleep(sleep_seconds)

    ordered = sorted(comments.values(), key=lambda item: item.comment_id)
    return {
        "available": True,
        "error": error,
        "source_url": page_url,
        "comments": ordered[:max_comments],
        "comment_count": comment_count,
        "loaded_count": min(len(ordered), max_comments),
        "pages": pages,
        "truncated": len(ordered) > max_comments or next_before is not None,
    }


def extract_comment_consensus(
    discussion: dict,
    *,
    post_id: int,
    post_url: str,
    published_at: str | None,
    pokemon_names: set[str],
    min_matching_comments: int = 3,
    min_distinct_authors: int = 3,
) -> list[dict]:
    """Return only mechanically strong, Pokémon-name comment consensus signals."""
    counts: dict[str, list[PublicComment]] = {}
    for comment in discussion.get("comments", []):
        candidate = extract_pokemon_candidate(comment.text, pokemon_names)
        if candidate:
            counts.setdefault(candidate, []).append(comment)

    signals: list[dict] = []
    for candidate, matching in counts.items():
        author_keys = {item.author_key for item in matching if item.author_key}
        if len(matching) < min_matching_comments or len(author_keys) < min_distinct_authors:
            continue
        signals.append(
            {
                "kind": "comment_consensus",
                "code": candidate,
                "code_normalized": candidate,
                "extraction_method": "discussion_widget_consensus_v1",
                "post_id": post_id,
                "source_url": post_url,
                "published_at": published_at,
                "evidence": (
                    f"公开讨论共 {discussion.get('comment_count') or discussion.get('loaded_count') or 0} 条评论；"
                    f"规范化后有 {len(matching)} 条答案一致，至少 {len(author_keys)} 个公开用户链接支持。"
                ),
                "media_urls": [],
                "needs_manual_review": False,
                "comment_count": discussion.get("comment_count"),
                "loaded_comment_count": discussion.get("loaded_count"),
                "matching_comment_count": len(matching),
                "distinct_author_count": len(author_keys),
                "matching_comment_id_sample": [item.comment_id for item in matching[:5]],
                "author_identity": "public_profile_link_lower_bound",
            }
        )
    return sorted(
        signals,
        key=lambda item: (item["distinct_author_count"], item["matching_comment_count"], item["code_normalized"]),
        reverse=True,
    )
