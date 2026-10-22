#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a vertical explainer from content/<issue>/storyboard.yaml.

Frames come from the HTML templates in video/templates/. Narration is
synthesized with edge-tts. Subtitles are built from the TTS word timings,
not from speech recognition. ffmpeg joins the frames and the audio.

    python video/render.py issue01
    python video/render.py issue01 --audio-only
    python video/render.py issue01 --fps 12

No API key. Needs network access for the free edge-tts voices, plus
ffmpeg/ffprobe on PATH and a Playwright Chromium install.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).resolve().parent / "templates"
TAIL_SECONDS = 0.5
NUMBER = re.compile(r"\d+(?:\.\d+)?")
PLACEHOLDER = re.compile(r"\{(C\d+)(?:\.(unit|year|text|value))?\}")
TOKEN = re.compile(r"__[A-Z0-9_]+__")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render an issue explainer video.")
    parser.add_argument("issue", nargs="?", default="issue01")
    parser.add_argument("--audio-only", action="store_true", help="Synthesize narration and print durations, then stop.")
    parser.add_argument("--fps", type=int, default=0, help="Override the storyboard frame rate.")
    args = parser.parse_args(argv[1:])

    issue_dir = ROOT / "content" / args.issue
    storyboard_path = issue_dir / "storyboard.yaml"
    if not storyboard_path.exists():
        print(f"Missing {storyboard_path}")
        return 1
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg and ffprobe must be on PATH.")
        return 1

    storyboard = load_yaml(storyboard_path)
    claims = {item["id"]: item for item in load_yaml(issue_dir / "claims.yaml")}
    scenes = list(storyboard.get("scenes") or [])
    scenes = ensure_end_card(scenes, args.issue)
    voice = str(storyboard.get("voice") or "zh-CN-YunxiNeural")
    fps = args.fps or int(storyboard.get("fps") or 12)
    tail = float(storyboard.get("tail_seconds") or TAIL_SECONDS)
    width = int(storyboard.get("width") or 1080)
    height = int(storyboard.get("height") or 1920)
    if storyboard.get("format", "vertical") != "vertical":
        print("This prototype renders the vertical 1080x1920 frame.")
        return 1

    prepared = []
    for index, scene in enumerate(scenes, start=1):
        narration, _used = resolve_narration(str(scene.get("narration") or ""), claims)
        prepared.append({
            "index": index,
            "scene": scene,
            "narration": narration,
            "id": str(scene.get("id") or f"s{index:02d}"),
        })

    work = ROOT / "out" / "work" / args.issue
    if work.exists():
        shutil.rmtree(work)
    audio_dir = work / "audio"
    html_dir = work / "html"
    frame_dir = work / "frames"
    preview_dir = ROOT / "out" / "preview" / args.issue
    for path in (audio_dir, html_dir, frame_dir, preview_dir):
        path.mkdir(parents=True, exist_ok=True)

    print(f"Synthesizing {len(prepared)} scenes with {voice}")
    timings = asyncio.run(synthesize_all(prepared, voice, audio_dir))

    master_cues = []
    cursor = 0.0
    padded_paths = []
    for item, words in zip(prepared, timings):
        voice_path = audio_dir / f"{item['id']}.mp3"
        padded_path = audio_dir / f"{item['id']}.wav"
        pad_audio(voice_path, padded_path, tail)
        voice_duration = media_duration(voice_path)
        padded_duration = media_duration(padded_path)
        cues = cues_from_words(words, item["narration"], voice_duration)
        item["cues"] = cues
        item["voice_duration"] = voice_duration
        item["duration"] = padded_duration
        for start, end, text in cues:
            master_cues.append((cursor + start, cursor + end, text))
        print(f"  {item['id']} speech {voice_duration:.2f}s  scene {padded_duration:.2f}s")
        cursor += padded_duration
        padded_paths.append(padded_path)

    print(f"Total duration {cursor:.2f}s")
    srt_path = ROOT / "out" / f"{args.issue}-vertical.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    write_srt(master_cues, srt_path)
    print(f"Wrote {srt_path.relative_to(ROOT)}")
    if args.audio_only:
        return 0

    shutil.copyfile(TEMPLATES / "tokens.css", html_dir / "tokens.css")
    frame_index = 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        for item in prepared:
            html_path = html_dir / f"{item['id']}.html"
            write_scene_html(item, claims, html_path, args.issue)
            page.goto(html_path.resolve().as_uri())
            page.wait_for_function("() => typeof window.setRenderTime === 'function'")
            page.evaluate("() => document.fonts.ready")
            page.wait_for_function(
                """() => {
                    const img = document.querySelector('img');
                    return !img || (img.complete && img.naturalWidth > 0);
                }"""
            )
            count = max(1, math.ceil(item["duration"] * fps - 1e-6))
            preview_at = max(0, count - 1 - round(0.35 * fps))
            for step in range(count):
                page.evaluate("(t) => window.setRenderTime(t)", step / fps)
                frame_path = frame_dir / f"{frame_index:05d}.png"
                page.screenshot(path=str(frame_path), type="png")
                if step == preview_at:
                    shutil.copyfile(frame_path, preview_dir / f"{item['id']}.png")
                frame_index += 1
            print(f"  frames {item['id']}: {count}")
        browser.close()

    all_wav = work / "all.wav"
    concat_audio(padded_paths, all_wav, audio_dir)
    out_mp4 = ROOT / "out" / f"{args.issue}-vertical.mp4"
    assemble(frame_dir, all_wav, out_mp4, fps)
    print(f"Wrote {out_mp4.relative_to(ROOT)}")
    return 0


def load_yaml(path: Path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def issue_number(issue: str) -> int:
    match = re.search(r"(\d+)$", issue)
    return int(match.group(1)) if match else 1


def end_card_text(issue: str) -> str:
    return f"本视频部分画面为 AI 生成 · 数据来源见网站第 {issue_number(issue)} 期"


def ensure_end_card(scenes: list[dict], issue: str) -> list[dict]:
    required = end_card_text(issue)
    for scene in scenes:
        if str(scene.get("text") or "").strip() == required:
            return scenes
    scenes = list(scenes)
    scenes.append({
        "id": "endcard",
        "template": "title-card",
        "kicker": "说明",
        "text": required,
        "subtitle": "",
        "narration": "本视频部分画面为人工智能生成。数据来源见网站第一期。",
    })
    return scenes


def parse_numbers(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in NUMBER.findall(str(value).replace(",", ""))]


def trim_number(number: float) -> str:
    if abs(number - round(number)) < 1e-8:
        return str(int(round(number)))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def display_value(value) -> str:
    raw = str(value).strip()
    numbers = parse_numbers(raw)
    if len(numbers) == 1 and re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return trim_number(numbers[0])
    if len(numbers) == 2 and re.search(r"[-–—~至]", raw):
        return trim_number(numbers[0]) + "–" + trim_number(numbers[1])
    return raw


def same_number(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-6 * max(1.0, abs(right))


def resolve_narration(text: str, claims: dict) -> tuple[str, list[dict]]:
    used: list[dict] = []

    def replace(match: re.Match) -> str:
        claim_id = match.group(1)
        field = match.group(2) or "value"
        claim = claims.get(claim_id)
        if claim is None:
            raise SystemExit(f"Narration references unknown claim {claim_id}")
        if str(claim.get("status", "")).strip() != "verified":
            raise SystemExit(f"{claim_id} is not verified; narration cannot use it")
        used.append(claim)
        if field == "value":
            return display_value(claim.get("value"))
        if field == "unit":
            return str(claim.get("unit") or "")
        if field == "year":
            if claim.get("year") is None:
                raise SystemExit(f"{claim_id} has no year")
            return str(claim.get("year"))
        if field == "text":
            return str(claim.get("text") or "")
        raise SystemExit(f"Unknown placeholder field {field}")

    resolved = PLACEHOLDER.sub(replace, text)
    leftover = re.findall(r"\{C\d+[^}]*\}", resolved)
    if leftover:
        raise SystemExit("Unresolved narration placeholders: " + ", ".join(leftover))
    allowed: list[float] = []
    for claim in used:
        allowed.extend(parse_numbers(claim.get("value")))
        allowed.extend(parse_numbers(claim.get("year")))
    for number in parse_numbers(resolved):
        if not any(same_number(number, item) for item in allowed):
            raise SystemExit(
                f"Narration number {number} is not in the referenced claims: {resolved}"
            )
    return resolved, used


def count_attrs(value) -> str:
    raw = str(value).strip()
    numbers = parse_numbers(raw)
    if len(numbers) != 1 or re.search(r"[-–—~至]", raw):
        return ""
    shown = trim_number(numbers[0])
    decimals = len(shown.split(".")[1]) if "." in shown else 0
    return f'data-count="{shown}" data-decimals="{decimals}"'


def number_size(shown: str) -> str:
    if len(shown) >= 5:
        return "md"
    if len(shown) >= 4:
        return "lg"
    return "xl"


def source_line(claims_in_order: list[dict]) -> str:
    parts = []
    seen = set()
    for claim in claims_in_order:
        if claim is None:
            continue
        key = (str(claim.get("source") or ""), str(claim.get("year") or ""))
        if key in seen:
            continue
        seen.add(key)
        if claim.get("year"):
            parts.append(f"来源 {claim.get('source')} · {claim.get('year')}")
        else:
            parts.append(f"来源 {claim.get('source')}")
    return "  /  ".join(parts)


def fallback_stills(issue: str) -> list[Path]:
    image_dir = ROOT / "static" / "img"
    return [
        image_dir / f"{issue}-cover-vertical.jpg",
        image_dir / f"{issue}-cover.jpg",
    ]


def resolve_asset(scene: dict, issue: str, html_path: Path) -> str:
    raw = str(scene.get("asset") or "").strip()
    candidates = []
    if raw:
        path = Path(raw)
        candidates.append(path if path.is_absolute() else ROOT / path)
    candidates.extend(fallback_stills(issue))
    for candidate in candidates:
        if candidate.exists():
            relative = Path(os.path.relpath(candidate.resolve(), html_path.parent.resolve()))
            return html.escape(relative.as_posix(), quote=True)
    raise SystemExit(
        "No b-roll still found. Expected "
        + " or ".join(str(path.relative_to(ROOT)) for path in fallback_stills(issue))
    )


def write_scene_html(item: dict, claims: dict, html_path: Path, issue: str) -> None:
    scene = item["scene"]
    template_name = str(scene.get("template") or "")
    template_path = TEMPLATES / f"{template_name}.html"
    if not template_path.exists():
        raise SystemExit(f"Unknown template {template_name}")
    template = template_path.read_text(encoding="utf-8")
    cues = [
        {"start": round(start, 3), "end": round(end, 3), "text": text}
        for start, end, text in item["cues"]
    ]
    tokens = {
        "__CUES__": json.dumps(cues, ensure_ascii=False),
        "__DURATION__": f"{item['duration']:.3f}",
        "__KICKER__": html.escape(str(scene.get("kicker") or "AI 科普工作室")),
        "__TEXT__": html.escape(str(scene.get("text") or "")),
        "__SUBTITLE__": html.escape(str(scene.get("subtitle") or "")),
        "__TITLE_CLASS__": "long" if len(str(scene.get("text") or "")) > 16 else "",
        "__LABEL__": html.escape(str(scene.get("label") or "")),
        "__CAPTION__": html.escape(str(scene.get("caption") or "")),
        "__PAN__": "1" if str(scene.get("pan") or "right") != "left" else "-1",
        "__VALUE__": "",
        "__UNIT__": "",
        "__ASIDE__": "",
        "__SOURCE_LINE__": "",
        "__COUNT_ATTRS__": "",
        "__SIZE__": "xl",
        "__IMAGE__": "",
    }
    if template_name == "big-number":
        claim_id = str(scene.get("claim") or "")
        claim = claims.get(claim_id)
        if claim is None:
            raise SystemExit(f"{item['id']} big-number missing claim")
        if str(claim.get("status", "")).strip() != "verified":
            raise SystemExit(f"{claim_id} is not verified")
        shown = display_value(claim.get("value"))
        aside_claim = None
        aside_id = str(scene.get("aside_claim") or "").strip()
        if aside_id:
            aside_claim = claims.get(aside_id)
            if aside_claim is None or str(aside_claim.get("status", "")).strip() != "verified":
                raise SystemExit(f"{item['id']} aside claim {aside_id} is not verified")
            aside = (
                f"{scene.get('aside_label') or ''} {display_value(aside_claim.get('value'))}"
                f" {aside_claim.get('unit') or ''}"
            ).strip()
        else:
            aside = ""
        tokens.update({
            "__VALUE__": html.escape(shown),
            "__UNIT__": html.escape(str(claim.get("unit") or "")),
            "__ASIDE__": html.escape(aside),
            "__SOURCE_LINE__": html.escape(source_line([claim, aside_claim])),
            "__COUNT_ATTRS__": count_attrs(claim.get("value")),
            "__SIZE__": number_size(shown),
        })
    if template_name == "broll":
        tokens["__IMAGE__"] = resolve_asset(scene, issue, html_path)
    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(key, value)
    leftover = TOKEN.findall(rendered)
    if leftover:
        raise SystemExit(f"Unfilled template tokens in {template_name}: {leftover}")
    html_path.write_text(rendered, encoding="utf-8", newline="\n")


async def synthesize_all(prepared: list[dict], voice: str, audio_dir: Path) -> list[list[dict]]:
    import edge_tts
    results = []
    for item in prepared:
        destination = audio_dir / f"{item['id']}.mp3"
        communicate = edge_tts.Communicate(
            item["narration"],
            voice,
            boundary="WordBoundary",
        )
        words = []
        with destination.open("wb") as handle:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    handle.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append(chunk)
        if destination.stat().st_size == 0:
            raise SystemExit(f"edge-tts returned empty audio for {item['id']}")
        results.append(words)
    return results


def cues_from_words(words: list[dict], narration: str, voice_duration: float) -> list[tuple[float, float, str]]:
    """Group word timings into readable lines, putting punctuation back from the script.

    edge-tts word events usually omit commas and periods, so the cue text is
    aligned against the narration instead of using the raw tokens alone.
    """
    if not words:
        print("WARN: no word timings; one subtitle covers the whole line")
        return [(0.0, max(voice_duration, 0.2), narration.strip())]

    aligned = []
    cursor = 0
    for word in words:
        token = str(word.get("text") or "").strip()
        if not token:
            continue
        found = narration.find(token, cursor)
        if found < 0:
            found = cursor
            piece = token
            cursor += len(token)
        else:
            if aligned and found > cursor:
                aligned[-1]["text"] += narration[cursor:found]
            piece = narration[found:found + len(token)]
            cursor = found + len(token)
        aligned.append({
            "start": word["offset"] / 10_000_000,
            "end": (word["offset"] + word["duration"]) / 10_000_000,
            "text": piece,
        })
    if aligned and cursor < len(narration):
        aligned[-1]["text"] += narration[cursor:]

    cues: list[tuple[float, float, str]] = []
    buffer: list[dict] = []

    def flush() -> None:
        if not buffer:
            return
        text = "".join(item["text"] for item in buffer).strip()
        start = buffer[0]["start"]
        end = buffer[-1]["end"]
        buffer.clear()
        if text:
            cues.append((start, max(end, start + 0.05), text))

    for item in aligned:
        buffer.append(item)
        text = "".join(part["text"] for part in buffer).strip()
        ends_sentence = text.endswith(("。", "！", "？"))
        ends_clause = text.endswith(("，", "；", "、"))
        if (ends_sentence and len(text) >= 8) or (ends_clause and len(text) >= 12) or len(text) >= 22:
            flush()
    flush()

    merged: list[tuple[float, float, str]] = []
    for start, end, text in cues:
        if merged and len(text) <= 2:
            prev_start, _prev_end, prev_text = merged[-1]
            merged[-1] = (prev_start, end, prev_text + text)
        else:
            merged.append((start, end, text))
    return merged or [(0.0, max(voice_duration, 0.2), narration.strip())]


def pad_audio(src: Path, dst: Path, tail: float) -> None:
    run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"apad=pad_dur={tail}",
        "-ar", "24000", "-ac", "1",
        "-c:a", "pcm_s16le",
        str(dst),
    ])


def concat_audio(parts: list[Path], destination: Path, audio_dir: Path) -> None:
    listing = audio_dir / "concat.txt"
    listing.write_text(
        "".join(f"file '{path.name}'\n" for path in parts),
        encoding="utf-8",
        newline="\n",
    )
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", listing.name, "-c", "copy", str(destination.resolve()),
    ], cwd=audio_dir)


def assemble(frame_dir: Path, audio: Path, destination: Path, fps: int) -> None:
    run([
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", "%05d.png",
        "-i", str(audio.resolve()),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        "-movflags", "+faststart",
        str(destination.resolve()),
    ], cwd=frame_dir)


def media_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"ffprobe failed for {path}")
    return float(completed.stdout.strip())


def run(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit("Command failed:\n" + " ".join(cmd) + "\n" + detail[-4000:])


def fmt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> None:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        if end <= start:
            end = start + 0.2
        blocks.append(f"{index}\n{fmt_timestamp(start)} --> {fmt_timestamp(end)}\n{text}\n")
    path.write_text("\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
