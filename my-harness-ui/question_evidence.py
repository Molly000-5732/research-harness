"""Structured question choices grounded in actual SDK reading-tool results.

No search or model client lives here. Acquisition remains with the official SDK.
The existing run reply stores the normalized choices, so session recovery and
confirmed-revision invalidation retain their original storage semantics.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit


def payload(reply, key="questions"):
    for block in reversed(re.findall(r"```json\s*(.*?)```", reply, re.S | re.I)):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get(key), list):
            return value
    return {}


def text(value, limit=4000):
    return value.strip()[:limit] if isinstance(value, str) else ""


def url(value):
    value = text(value, 2048)
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else ""
    except ValueError:
        return ""


def normalize(value):
    return re.sub(r"\s+", "", value).casefold()


def choices(reply, key="questions"):
    out = []
    for index, item in enumerate(payload(reply, key).get(key, [])[:6]):
        if not isinstance(item, dict) or not text(item.get("title"), 500):
            continue
        evidence = []
        for entry in item.get("evidence", [])[:8] if isinstance(item.get("evidence"), list) else []:
            if not isinstance(entry, dict) or not url(entry.get("url")):
                continue
            evidence.append({
                "title": text(entry.get("title"), 500), "url": url(entry.get("url")),
                "quote": text(entry.get("quote"), 1500), "locator": text(entry.get("locator"), 500),
                "reason": text(entry.get("reason"), 1500),
                "verified": entry.get("verified") is True,
                "receipt": text(entry.get("receipt"), 64),
            })
        out.append({"id": str(index + 1), "title": text(item.get("title"), 500),
                    "description": text(item.get("description")), "evidence": evidence})
    return out


def reading_receipts(events):
    calls = {}
    receipts = []
    for event in events:
        data = event.get("data") or {}
        if event.get("type") == "tool/call":
            calls[data.get("callId")] = (str(data.get("name", "")), data.get("arguments", ""))
        elif event.get("type") == "tool/result":
            message = data.get("message") or {}
            name, args = calls.get(message.get("toolCallId"), ("", ""))
            if not name or "search" in name.lower() or message.get("isError"):
                continue
            body = "\n".join(p.get("text", "") for p in message.get("content", []) if p.get("type") == "text")
            arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            receipts.append((body, arguments))
    return receipts


def grounded_reply(reply, events, previous=(), key="questions"):
    """Ignore model-provided verification flags; match quotes to tool output."""
    receipts = reading_receipts(events)
    old = {(e["url"], normalize(e["quote"])): e for prior in previous for stage_key in ("questions", "painpoints") for q in choices(prior, stage_key)
           for e in q["evidence"] if e["verified"] and e["receipt"]}
    items = choices(reply, key)
    for question in items:
        for entry in question["evidence"]:
            entry["verified"], entry["receipt"] = False, ""
            quote = normalize(entry["quote"])
            # Short strings and search snippets cannot establish a passage citation.
            if len(quote) < 30 or not entry["locator"]:
                continue
            prior = old.get((entry["url"], quote))
            if prior:
                entry.update(verified=True, receipt=prior["receipt"])
                continue
            for body, arguments in receipts:
                if quote in normalize(body) and entry["url"] in body + arguments:
                    entry.update(verified=True, receipt=hashlib.sha256(body.encode()).hexdigest())
                    break
    source = payload(reply, key)
    normalized = {"papers": source.get("papers", []), key: items}
    prose = re.sub(r"```json\s*.*?```", "", reply, flags=re.S | re.I).strip()
    return prose + "\n\n```json\n" + json.dumps(normalized, ensure_ascii=False) + "\n```"


def selected_content(question):
    lines = [question["title"], question["description"], "文献依据："]
    for entry in question["evidence"]:
        if entry["verified"]:
            lines.append(f"{entry['title']}\n{entry['url']}\n位置：{entry['locator']}\n原文：{entry['quote']}\n依据：{entry['reason']}")
    return "\n\n".join(lines)
