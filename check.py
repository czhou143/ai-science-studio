#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check an issue's evidence package.

Usage:
    python check.py
    python check.py issue01

ERROR (exit code 1):
- a claim id cited by the article, data.csv, or storyboard is missing
- a source id used by a claim, the article, or data.csv is missing
- a verified claim has no excerpt
- a data.csv value does not match the linked claim value
- a claim record is missing a required field or uses an illegal enum

WARN (exit code stays 0):
- draft claims
- claims not used by the article, data.csv, or storyboard
- claim years that start before 2020

Writes content/<issue>/review.md.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD_YEAR_BEFORE = 2020
KINDS = {"measured", "estimated", "projected", "qualitative"}
STATUSES = {"verified", "draft"}
REQUIRED_FIELDS = ("id", "text", "kind", "scope", "source", "status")
CLAIM_ID = re.compile(r"^C\d+$")
SOURCE_ID = re.compile(r"^S\d+$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def main(argv: list[str]) -> int:
    issue = argv[1] if len(argv) > 1 else "issue01"
    issue_dir = ROOT / "content" / issue
    if not issue_dir.is_dir():
        print(f"ERROR: content directory not found: {issue_dir}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    claims = load_claims(issue_dir / "claims.yaml", errors)
    sources = load_source_ids(issue_dir / "sources.csv", errors)
    article = read_text(issue_dir / "article.md")
    data_rows = load_data_rows(issue_dir / "data.csv", errors)
    storyboard = read_text(issue_dir / "storyboard.yaml")

    by_id = {}
    for claim in claims:
        claim_id = str(claim.get("id", "")).strip()
        if claim_id in by_id:
            errors.append(f"claims.yaml 里 {claim_id} 重复出现")
        if claim_id:
            by_id[claim_id] = claim

    referenced: set[str] = set()
    for claim_id in re.findall(r"\[(C\d+)\]", article):
        referenced.add(claim_id)
        if claim_id not in by_id:
            errors.append(f"正文引用了 [{claim_id}]，但 claims.yaml 里没有这条主张")

    for claim_id in storyboard_claim_ids(storyboard):
        referenced.add(claim_id)
        if claim_id not in by_id:
            errors.append(f"分镜引用了 {claim_id}，但 claims.yaml 里没有这条主张")

    for index, row in enumerate(data_rows, start=1):
        linked = split_claim_ids(row.get("claim", ""))
        if not linked:
            errors.append(f"data.csv 第 {index} 行没有 claim 编号，无法核对数值")
            continue
        for claim_id in linked:
            referenced.add(claim_id)
            if claim_id not in by_id:
                errors.append(
                    f"data.csv 第 {index} 行引用了 {claim_id}，但 claims.yaml 里没有这条主张"
                )
        known = [by_id[item] for item in linked if item in by_id]
        if known and not values_match(row.get("数值", ""), [item.get("value") for item in known]):
            shown = "、".join(format_value(item.get("value")) for item in known)
            errors.append(
                f"data.csv 第 {index} 行数值「{row.get('数值', '').strip()}」"
                f"与主张 {', '.join(linked)} 的数值「{shown}」不一致"
            )

    for source_id in re.findall(r"\[(S\d+)\]", article):
        if source_id not in sources:
            errors.append(f"正文引用了 [{source_id}]，但 sources.csv 里没有这个来源")

    for index, row in enumerate(data_rows, start=1):
        for source_id in re.findall(r"\[?(S\d+)\]?", row.get("来源编号", "")):
            if source_id not in sources:
                errors.append(
                    f"data.csv 第 {index} 行的来源 {source_id} 不在 sources.csv 里"
                )

    for claim in claims:
        claim_id = str(claim.get("id", "")).strip() or "（无编号）"
        source_id = str(claim.get("source", "")).strip()
        if source_id and source_id not in sources:
            errors.append(f"{claim_id} 的来源 {source_id} 不在 sources.csv 里")
        status = str(claim.get("status", "")).strip()
        excerpt = claim.get("excerpt")
        excerpt_text = excerpt.strip() if isinstance(excerpt, str) else ""
        if status == "verified" and not excerpt_text:
            errors.append(f"{claim_id} 标记为 verified，但没有摘录")
        if status == "draft":
            warnings.append(f"{claim_id} 仍是 draft：{claim.get('text', '')}")
        if claim_id not in referenced and claim_id != "（无编号）":
            warnings.append(f"{claim_id} 没有被正文、data.csv 或分镜使用")
        year = starting_year(claim.get("year"))
        if year is not None and year < OLD_YEAR_BEFORE:
            warnings.append(f"{claim_id} 的年份 {claim.get('year')} 早于 {OLD_YEAR_BEFORE}")

    review = render_review(issue, claims, errors, warnings)
    review_path = issue_dir / "review.md"
    review_path.write_text(review, encoding="utf-8", newline="\n")

    print(f"issue: {issue}")
    print(f"claims: {len(claims)}")
    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")
    for message in errors:
        print("ERROR " + message)
    for message in warnings:
        print("WARN " + message)
    print(f"wrote {review_path.relative_to(ROOT)}")
    return 1 if errors else 0


def load_claims(path: Path, errors: list[str]) -> list[dict]:
    if not path.exists():
        errors.append(f"缺少 {path.name}")
        return []
    try:
        import yaml
    except ImportError:
        errors.append("未安装 PyYAML，无法读取 claims.yaml")
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        errors.append("claims.yaml 的顶层必须是列表")
        return []
    cleaned = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            errors.append(f"claims.yaml 第 {index} 条不是记录")
            continue
        claim_id = str(item.get("id", "")).strip()
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"{claim_id or '第 ' + str(index) + ' 条'} 缺少字段 {field}")
        if claim_id and not CLAIM_ID.match(claim_id):
            errors.append(f"主张编号非法：{claim_id}")
        kind = str(item.get("kind", "")).strip()
        if kind and kind not in KINDS:
            errors.append(f"{claim_id} 的 kind 非法：{kind}")
        status = str(item.get("status", "")).strip()
        if status and status not in STATUSES:
            errors.append(f"{claim_id} 的 status 非法：{status}")
        source = str(item.get("source", "")).strip()
        if source and not SOURCE_ID.match(source):
            errors.append(f"{claim_id} 的 source 非法：{source}")
        cleaned.append(item)
    return cleaned


def load_source_ids(path: Path, errors: list[str]) -> set[str]:
    if not path.exists():
        errors.append("缺少 sources.csv")
        return set()
    ids = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_id = (row.get("id") or "").strip()
            if source_id:
                ids.add(source_id)
    return ids


def load_data_rows(path: Path, errors: list[str]) -> list[dict]:
    if not path.exists():
        errors.append("缺少 data.csv")
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def storyboard_claim_ids(text: str) -> list[str]:
    if not text:
        return []
    found = re.findall(r"\{(C\d+)(?:\.[A-Za-z_]+)?\}", text)
    found += re.findall(r"(?m)^[ \t-]*(?:claim|aside_claim):\s*(C\d+)\s*$", text)
    return found


def split_claim_ids(raw: str) -> list[str]:
    return [part for part in re.split(r"[;\s,]+", (raw or "").strip()) if part]


def parse_numbers(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in NUMBER.findall(str(value).replace(",", ""))]


def same_number(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-6 * max(1.0, abs(right))


def values_match(data_value, claim_values) -> bool:
    data_numbers = parse_numbers(data_value)
    claim_numbers: list[float] = []
    for value in claim_values:
        claim_numbers.extend(parse_numbers(value))
    if not data_numbers or not claim_numbers:
        return False
    if len(data_numbers) == len(claim_numbers) and all(
        same_number(left, right)
        for left, right in zip(sorted(data_numbers), sorted(claim_numbers))
    ):
        return True
    if len(data_numbers) >= 2 and all(
        any(same_number(item, claim) for claim in claim_numbers) for item in data_numbers
    ):
        return same_number(min(data_numbers), min(claim_numbers)) and same_number(
            max(data_numbers), max(claim_numbers)
        )
    return False


def format_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def starting_year(value) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def render_review(issue: str, claims: list[dict], errors: list[str], warnings: list[str]) -> str:
    verified = sum(1 for claim in claims if str(claim.get("status", "")).strip() == "verified")
    draft = sum(1 for claim in claims if str(claim.get("status", "")).strip() == "draft")
    lines = [
        f"# {issue} 证据检查",
        "",
        f"生成日期：{date.today().isoformat()}",
        "",
        f"- 主张 {len(claims)} 条：verified {verified}，draft {draft}",
        f"- ERROR {len(errors)}",
        f"- WARN {len(warnings)}",
        f"- 旧年份阈值：起始年早于 {OLD_YEAR_BEFORE}",
        "- 未使用：正文、data.csv 的 claim 列、分镜里都没有出现的主张",
        "",
        "## ERROR",
        "",
    ]
    lines.extend(errors or ["无"])
    lines.extend(["", "## WARN", ""])
    lines.extend(warnings or ["无"])
    lines.extend(["", "## 主张", ""])
    lines.append("| id | status | kind | value | source |")
    lines.append("| --- | --- | --- | --- | --- |")
    for claim in claims:
        lines.append(
            "| {id} | {status} | {kind} | {value} | {source} |".format(
                id=claim.get("id", ""),
                status=claim.get("status", ""),
                kind=claim.get("kind", ""),
                value=str(claim.get("value", "")).replace("|", "/"),
                source=claim.get("source", ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
