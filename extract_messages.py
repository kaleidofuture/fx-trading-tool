#!/usr/bin/env python3
"""Extract user/assistant conversation from a Claude Code JSONL transcript."""

import json
import sys
from datetime import datetime

INPUT = "C:/Users/mitoi/.claude/projects/c--Users-mitoi-Desktop-Projects-20260215-skills-sh-----/e7327ce3-85fd-4029-8d5f-35a39fb3eefd.jsonl"
OUTPUT = "c:/Users/mitoi/Desktop/Projects/20260308_本気でFXで稼ぐAIツール開発してみた/JOURNAL_MESSAGES.md"


def format_ts(ts_str):
    """Format ISO timestamp to readable string."""
    if not ts_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts_str


def extract_user_text(message):
    """Extract text from user message content."""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block["text"])
    return "\n".join(texts)


def extract_assistant_content(message):
    """Extract text and tool-use summaries from assistant message content."""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text)
        elif btype == "tool_use":
            tool_name = block.get("name", "unknown_tool")
            # Brief summary of tool call
            inp = block.get("input", {})
            if tool_name in ("Read", "Glob", "Grep"):
                target = inp.get("file_path") or inp.get("pattern") or inp.get("path", "")
                parts.append(f"[Tool: {tool_name} - {target}]")
            elif tool_name == "Bash":
                cmd = inp.get("command", "")
                # Truncate long commands
                if len(cmd) > 120:
                    cmd = cmd[:120] + "..."
                parts.append(f"[Tool: Bash - `{cmd}`]")
            elif tool_name in ("Edit", "Write"):
                fp = inp.get("file_path", "")
                parts.append(f"[Tool: {tool_name} - {fp}]")
            elif tool_name == "WebSearch":
                query = inp.get("query", "")
                parts.append(f"[Tool: WebSearch - {query}]")
            elif tool_name == "WebFetch":
                url = inp.get("url", "")
                parts.append(f"[Tool: WebFetch - {url}]")
            else:
                parts.append(f"[Tool: {tool_name}]")
        # Skip 'thinking' blocks
    return "\n".join(parts)


def main():
    # Group consecutive assistant messages by parentUuid chain
    # But simpler: just emit each user and assistant message in order

    messages = []  # list of (timestamp, role, text)

    with open(INPUT, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            ts = obj.get("timestamp", "")

            if msg_type == "user":
                text = extract_user_text(obj.get("message", {}))
                if text.strip():
                    messages.append((ts, "user", text.strip()))

            elif msg_type == "assistant":
                text = extract_assistant_content(obj.get("message", {}))
                if text.strip():
                    messages.append((ts, "assistant", text.strip()))

    # Now merge consecutive assistant messages (they often come in chunks)
    merged = []
    for ts, role, text in messages:
        if merged and merged[-1][1] == role == "assistant":
            # Append to previous assistant message
            merged[-1] = (merged[-1][0], role, merged[-1][2] + "\n" + text)
        else:
            merged.append((ts, role, text))

    # Write output
    msg_num = 0
    with open(OUTPUT, "w", encoding="utf-8") as out:
        out.write("# FX AI Tool Development - Conversation Transcript\n\n")
        out.write(f"Extracted from session `e7327ce3-85fd-4029-8d5f-35a39fb3eefd`\n\n")
        out.write("---\n\n")

        i = 0
        while i < len(merged):
            ts, role, text = merged[i]

            if role == "user":
                msg_num += 1
                out.write(f"### Message {msg_num} [{format_ts(ts)}]\n\n")
                out.write(f"**User**: {text}\n\n")

                # Check if next is assistant response
                if i + 1 < len(merged) and merged[i + 1][1] == "assistant":
                    i += 1
                    _, _, atext = merged[i]
                    out.write(f"**Assistant**: {atext}\n\n")

                out.write("---\n\n")
            else:
                # Standalone assistant message (no preceding user)
                msg_num += 1
                out.write(f"### Message {msg_num} [{format_ts(ts)}]\n\n")
                out.write(f"**Assistant**: {text}\n\n")
                out.write("---\n\n")

            i += 1

    print(f"Done. Wrote {msg_num} message groups to {OUTPUT}")
    print(f"Total raw entries: {len(messages)}, merged: {len(merged)}")


if __name__ == "__main__":
    main()
