#!/usr/bin/env python3
"""One-off backfill: re-fetch full summaries for signals truncated by the
old hard 200/300-char cuts.

How it works: for each stored signal whose summary looks truncated (length
at one of the old cut points, no ellipsis), fetch the article URL and pull
the description from its <meta> tags (og:description > description >
twitter:description). The new text is cleaned and smart-truncated at the
new 400-char limit, and the row is updated only when the result is longer
than what is stored.

Usage:
    .venv/bin/python scripts/backfill_summaries.py            # dry run
    .venv/bin/python scripts/backfill_summaries.py --apply    # write to DB
"""
import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import feedparser
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RSS_FEEDS  # noqa: E402
from src.signals.base import smart_truncate  # noqa: E402
from src.signals.news_source import clean_html_text  # noqa: E402
from src.storage import get_connection, get_setting  # noqa: E402

logger = logging.getLogger("backfill_summaries")

# Old hard cut points (news/research_view: 200, ai_triage: 300).
_OLD_CUT_LENGTHS = (200, 300)

_META_TAG_RE = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
_DESC_KEYS = ("og:description", "description", "twitter:description")

# wallstreetcn article pages are JS shells; their JSON API has the full text.
_WSCN_ARTICLE_RE = re.compile(r"^https?://(?:www\.)?wallstreetcn\.com/articles/(\d+)")
_WSCN_API = "https://api-one.wallstcn.com/apiv1/content/articles/{}?extract=0"

# Browser-like UA: some news sites reject obvious bot agents.
_FETCH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def extract_description(html: str) -> str | None:
    """Pull the best description from <meta> tags, any attribute order."""
    found: dict[str, str] = {}
    for tag in _META_TAG_RE.findall(html):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        key = attrs.get("property", attrs.get("name", "")).lower()
        content = (attrs.get("content") or "").strip()
        if key in _DESC_KEYS and content and key not in found:
            found[key] = content
    for key in _DESC_KEYS:
        if key in found:
            return found[key]
    return None


def looks_truncated(summary: str | None) -> bool:
    """True when the summary sits at an old hard-cut length without an
    ellipsis — i.e. it was chopped mid-thought by the old code."""
    if not summary:
        return False
    if summary.endswith("…"):
        return False
    return len(summary) in _OLD_CUT_LENGTHS


def fetch_description(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("fetch failed %s: %s", url, e)
        return None
    return extract_description(resp.text)


def wscn_article_id(url: str) -> str | None:
    m = _WSCN_ARTICLE_RE.match(url or "")
    return m.group(1) if m else None


def parse_wscn_article(payload: dict) -> str | None:
    """Full article text preferred; content_short as fallback."""
    data = payload.get("data") or {}
    content = clean_html_text(data.get("content") or "")
    if content:
        return content
    return clean_html_text(data.get("content_short") or "") or None


def fetch_wscn_summary(client: httpx.Client, url: str) -> str | None:
    article_id = wscn_article_id(url)
    if not article_id:
        return None
    try:
        resp = client.get(_WSCN_API.format(article_id))
        resp.raise_for_status()
        return parse_wscn_article(resp.json())
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("wscn api failed %s: %s", url, e)
        return None


def rss_items_from_xml(xml_text: str) -> dict[str, str]:
    """Map article link -> cleaned full summary from one RSS feed body."""
    try:
        feed = feedparser.parse(xml_text)
    except Exception:
        return {}
    items: dict[str, str] = {}
    for entry in feed.entries:
        link = getattr(entry, "link", "") or ""
        raw = getattr(entry, "summary", getattr(entry, "description", "")) or ""
        text = clean_html_text(raw)
        if link.startswith(("http://", "https://")) and text:
            items[link] = text
    return items


def configured_rss_urls() -> list[str]:
    """Built-in feeds plus custom rss sources from the settings page."""
    urls = list(RSS_FEEDS)
    try:
        for entry in json.loads(get_setting("sources_config", "") or "[]"):
            if not entry.get("builtin", False) and entry.get("type") == "rss" and entry.get("url"):
                urls.append(entry["url"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("sources_config 解析失败，只用内置 RSS 源")
    return urls


def collect_rss_summaries(client: httpx.Client) -> dict[str, str]:
    """Fetch every configured RSS feed once; url -> full summary."""
    items: dict[str, str] = {}
    for feed_url in configured_rss_urls():
        try:
            resp = client.get(feed_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("RSS 拉取失败 %s: %s", feed_url, e)
            continue
        items.update(rss_items_from_xml(resp.text))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write updates to the DB (default: dry run)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between fetches")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, quarter, source, title, url, summary FROM signals WHERE url IS NOT NULL"
        ).fetchall()

    targets = [dict(r) for r in rows if looks_truncated(r["summary"])]
    print(f"候选信号：{len(targets)} 条（概要停留在旧截断长度）")
    if not targets:
        return 0

    updated = skipped = failed = rss_hits = 0
    with httpx.Client(
        headers={"User-Agent": _FETCH_UA}, timeout=15.0, follow_redirects=True
    ) as client:
        rss_map = collect_rss_summaries(client)
        print(f"RSS 源共提供 {len(rss_map)} 条最新条目")
        for i, sig in enumerate(targets):
            raw = rss_map.get(sig["url"])
            if raw:
                rss_hits += 1
            else:
                time.sleep(args.delay)
                raw = fetch_wscn_summary(client, sig["url"]) or fetch_description(client, sig["url"])
            if not raw:
                failed += 1
                print(f"[失败] {sig['source']} | {sig['title'][:40]} | {sig['url']}")
                continue
            new_summary = smart_truncate(clean_html_text(raw))
            old_len = len(sig["summary"] or "")
            if len(new_summary) <= old_len:
                skipped += 1
                print(f"[跳过] 新概要不比旧的长 ({old_len}字) | {sig['title'][:40]}")
                continue
            if args.apply:
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE signals SET summary = ? WHERE quarter = ? AND id = ?",
                        (new_summary, sig["quarter"], sig["id"]),
                    )
                    conn.commit()  # get_connection closes without committing
            updated += 1
            print(f"[{'已更新' if args.apply else '将更新'}] {old_len} -> {len(new_summary)}字 | {sig['title'][:40]}")

    mode = "实际写入" if args.apply else "试运行（未写入，加 --apply 生效）"
    print(f"\n完成（{mode}）：更新 {updated}（其中 RSS 命中 {rss_hits}），跳过 {skipped}，失败 {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
