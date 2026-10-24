#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a vertical explainer from content/<issue>/storyboard.yaml.

The picture is one HTML film. Narration is synthesized with edge-tts.
Subtitles come from the TTS word timings, not from speech recognition.
ffmpeg joins the frames and the audio.

    python video/render.py issue01
    python video/render.py issue01 --audio-only
    python video/render.py issue01 --stills

No API key. Needs network access for the free edge-tts voices, plus
ffmpeg/ffprobe on PATH and a Playwright Chromium install.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
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
KIND_LABEL = {
    "estimated": "估算",
    "measured": "实测",
    "projected": "预测",
    "qualitative": "",
}
TEMPLATES_OK = {"opener", "split", "bars", "race", "sparse", "lines", "end"}
SINGLE_NUMBER = {"split", "bars", "sparse"}
CLAIM_KEYS = {
    "split": ("left", "right"),
    "bars": ("left", "right"),
    "sparse": ("total", "active"),
}
VISIBLE_FIELDS = (
    "kicker", "text", "subtitle", "label", "caption", "stamp", "note", "footnote",
    "left_label", "right_label", "left_title", "right_title", "left_tag", "right_tag",
    "total_label", "active_label",
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render an issue explainer video.")
    parser.add_argument("issue", nargs="?", default="issue01")
    parser.add_argument("--audio-only", action="store_true", help="Synthesize narration and print durations, then stop.")
    parser.add_argument("--stills", action="store_true", help="Write one late frame per scene and stop.")
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
    fps = args.fps or int(storyboard.get("fps") or 24)
    tail = float(storyboard.get("tail_seconds") or TAIL_SECONDS)
    width = int(storyboard.get("width") or 1080)
    height = int(storyboard.get("height") or 1920)
    if storyboard.get("format", "vertical") != "vertical":
        print("This prototype renders the vertical 1080x1920 frame.")
        return 1
    if width % 2 or height % 2:
        print("Frame size must be even.")
        return 1

    prepared = []
    for index, scene in enumerate(scenes, start=1):
        validate_scene(scene, claims, args.issue)
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
        voice_duration = media_duration(voice_path)
        pad_audio(voice_path, padded_path, tail, voice_duration)
        padded_duration = media_duration(padded_path)
        cues = cues_from_words(words, item["narration"], voice_duration)
        item["cues"] = cues
        item["voice_duration"] = voice_duration
        item["duration"] = padded_duration
        item["start"] = cursor
        for start, end, text in cues:
            master_cues.append((cursor + start, cursor + end, text))
        print(f"  {item['id']} speech {voice_duration:.2f}s  scene {padded_duration:.2f}s  {item['narration']}")
        cursor += padded_duration
        padded_paths.append(padded_path)

    print(f"Total duration {cursor:.2f}s")
    if cursor < 54 or cursor > 66:
        print(f"WARN: duration {cursor:.2f}s is outside 54-66s")
    srt_path = ROOT / "out" / f"{args.issue}-vertical.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    write_srt(master_cues, srt_path)
    print(f"Wrote {srt_path.relative_to(ROOT)}")
    if args.audio_only:
        return 0

    film = build_film(prepared, claims, args.issue, width, height, cursor)
    shutil.copyfile(TEMPLATES / "tokens.css", html_dir / "tokens.css")
    html_path = html_dir / "film.html"
    write_film(film, html_path)
    render_frames(
        film, html_path, preview_dir, frame_dir, fps, width, height, stills_only=args.stills,
    )
    if args.stills:
        print(f"Wrote stills to {preview_dir.relative_to(ROOT)}")
        return 0

    all_wav = work / "all.wav"
    concat_audio(padded_paths, all_wav, audio_dir)
    out_mp4 = ROOT / "out" / f"{args.issue}-vertical.mp4"
    assemble(frame_dir, all_wav, out_mp4, fps, cursor)
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
        "template": "end",
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


def resolve_plain(value, claims: dict, issue: str) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip() == end_card_text(issue):
        return text.strip()
    resolved, _used = resolve_narration(text, claims)
    return resolved


def is_single_number(value) -> bool:
    raw = str(value).strip()
    numbers = parse_numbers(raw)
    return len(numbers) == 1 and re.search(r"[-–—~至]", raw) is None


def claim_card(claim: dict) -> dict:
    shown = display_value(claim.get("value"))
    numbers = parse_numbers(claim.get("value"))
    single = is_single_number(claim.get("value"))
    decimals = len(shown.split(".")[1]) if single and "." in shown else 0
    kind = str(claim.get("kind") or "")
    year = claim.get("year")
    return {
        "id": claim.get("id"),
        "value": shown,
        "unit": str(claim.get("unit") or ""),
        "year": "" if year is None else str(year),
        "kind": kind,
        "kindLabel": KIND_LABEL.get(kind, ""),
        "source": str(claim.get("source") or ""),
        "number": numbers[0] if single else None,
        "decimals": decimals,
    }


def bound_claim(scene: dict, key: str, claims: dict, single: bool) -> dict | None:
    raw = scene.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    claim_id = str(raw).strip()
    claim = claims.get(claim_id)
    if claim is None:
        raise SystemExit(f"{scene.get('id')} references unknown claim {claim_id}")
    if str(claim.get("status", "")).strip() != "verified":
        raise SystemExit(f"{claim_id} is not verified")
    card = claim_card(claim)
    if single and card["number"] is None:
        raise SystemExit(f"{claim_id} must be a single number in this scene")
    return card


def visible_strings(scene: dict) -> list[str]:
    found = []
    for key in VISIBLE_FIELDS:
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    lines = scene.get("lines") or []
    if isinstance(lines, str):
        lines = [lines]
    for line in lines:
        if str(line).strip():
            found.append(str(line))
    return found


def validate_scene(scene: dict, claims: dict, issue: str) -> None:
    template = str(scene.get("template") or "")
    if template not in TEMPLATES_OK:
        raise SystemExit(f"Unknown template {template}")
    for key in CLAIM_KEYS.get(template, ()):
        if bound_claim(scene, key, claims, template in SINGLE_NUMBER) is None:
            raise SystemExit(f"{scene.get('id')} missing {key}")
    if template == "lines" and not (scene.get("lines") or []):
        raise SystemExit(f"{scene.get('id')} has no lines")
    if template == "end" and str(scene.get("text") or "").strip() != end_card_text(issue):
        raise SystemExit(f"{scene.get('id')} end card text does not match the required sentence")
    for text in visible_strings(scene):
        resolve_plain(text, claims, issue)


def build_film(prepared: list[dict], claims: dict, issue: str, width: int, height: int, duration: float) -> dict:
    payload = []
    for item in prepared:
        scene = item["scene"]
        template = str(scene.get("template") or "")
        single = template in SINGLE_NUMBER
        lines = scene.get("lines") or []
        if isinstance(lines, str):
            lines = [lines]
        entry = {
            "id": item["id"],
            "template": template,
            "start": round(item["start"], 3),
            "end": round(item["start"] + item["duration"], 3),
            "kicker": resolve_plain(scene.get("kicker"), claims, issue),
            "title": resolve_plain(scene.get("text"), claims, issue),
            "deck": resolve_plain(scene.get("subtitle"), claims, issue),
            "stamp": resolve_plain(scene.get("stamp"), claims, issue),
            "note": resolve_plain(scene.get("note"), claims, issue),
            "footnote": resolve_plain(scene.get("footnote"), claims, issue),
            "leftLabel": resolve_plain(scene.get("left_label"), claims, issue),
            "rightLabel": resolve_plain(scene.get("right_label"), claims, issue),
            "leftTitle": resolve_plain(scene.get("left_title"), claims, issue),
            "rightTitle": resolve_plain(scene.get("right_title"), claims, issue),
            "leftTag": resolve_plain(scene.get("left_tag"), claims, issue),
            "rightTag": resolve_plain(scene.get("right_tag"), claims, issue),
            "totalLabel": resolve_plain(scene.get("total_label"), claims, issue),
            "activeLabel": resolve_plain(scene.get("active_label"), claims, issue),
            "lines": [resolve_plain(line, claims, issue) for line in lines],
            "left": bound_claim(scene, "left", claims, single),
            "right": bound_claim(scene, "right", claims, single),
            "total": bound_claim(scene, "total", claims, single),
            "active": bound_claim(scene, "active", claims, single),
            "cues": [
                {"start": round(start, 3), "end": round(end, 3), "text": text}
                for start, end, text in item["cues"]
            ],
        }
        payload.append(entry)
        bits = []
        for key in ("left", "right", "total", "active"):
            card = entry[key]
            if card:
                bits.append(f"{key} {card['id']}={card['value']}{card['unit']}")
        if bits:
            print("  " + item["id"] + " " + " ".join(bits))
    return {"width": width, "height": height, "duration": round(duration, 3), "scenes": payload}


def write_film(film: dict, html_path: Path) -> None:
    template = (TEMPLATES / "film.html").read_text(encoding="utf-8")
    blob = json.dumps(film, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    if "__FILM__" not in template:
        raise SystemExit("film.html is missing __FILM__")
    html_path.write_text(template.replace("__FILM__", blob), encoding="utf-8", newline="\n")


def render_frames(film, html_path, preview_dir, frame_dir, fps, width, height, stills_only: bool) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--force-color-profile=srgb",
                "--font-render-hinting=none",
            ],
        )
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri())
        page.wait_for_function("() => typeof window.setRenderTime === 'function'")
        page.evaluate("() => document.fonts.ready")
        shots = []
        if stills_only:
            for scene in film["scenes"]:
                late = scene["start"] + max(0.0, (scene["end"] - scene["start"]) - 0.35)
                early = scene["start"] + min(1.0, (scene["end"] - scene["start"]) * 0.28)
                shots.append((preview_dir / f"{scene['id']}-in.png", early))
                shots.append((preview_dir / f"{scene['id']}.png", late))
        else:
            count = max(1, math.ceil(film["duration"] * fps - 1e-6))
            saved = set()
            for step in range(count):
                t = step / fps
                page.evaluate("(t) => window.setRenderTime(t)", t)
                frame_path = frame_dir / f"{step:05d}.png"
                page.screenshot(path=str(frame_path), type="png")
                for scene in film["scenes"]:
                    late = scene["start"] + max(0.0, (scene["end"] - scene["start"]) - 0.35)
                    if scene["id"] not in saved and t >= late:
                        shutil.copyfile(frame_path, preview_dir / f"{scene['id']}.png")
                        saved.add(scene["id"])
                if step % 120 == 0:
                    print(f"  frame {step}/{count}")
            print(f"  frame {count}/{count}")
            browser.close()
            return
        for path, t in shots:
            page.evaluate("(t) => window.setRenderTime(t)", t)
            page.screenshot(path=str(path), type="png")
            print(f"  still {path.name} at {t:.2f}s")
        browser.close()


def cache_paths(voice: str, text: str) -> tuple[Path, Path]:
    key = hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()[:20]
    folder = ROOT / ".cache" / "tts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.mp3", folder / f"{key}.json"


async def synthesize_all(prepared: list[dict], voice: str, audio_dir: Path) -> list[list[dict]]:
    import edge_tts
    results = []
    for item in prepared:
        destination = audio_dir / f"{item['id']}.mp3"
        cached_mp3, cached_meta = cache_paths(voice, item["narration"])
        if cached_mp3.exists() and cached_meta.exists() and cached_mp3.stat().st_size > 0:
            try:
                words = json.loads(cached_meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                words = None
            if isinstance(words, list):
                shutil.copyfile(cached_mp3, destination)
                results.append(words)
                continue
        communicate = edge_tts.Communicate(item["narration"], voice, boundary="WordBoundary")
        words = []
        with destination.open("wb") as handle:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    handle.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({
                        "offset": int(chunk["offset"]),
                        "duration": int(chunk["duration"]),
                        "text": str(chunk.get("text") or ""),
                    })
        if destination.stat().st_size == 0:
            raise SystemExit(f"edge-tts returned empty audio for {item['id']}")
        shutil.copyfile(destination, cached_mp3)
        cached_meta.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8", newline="\n")
        results.append(words)
    return results


def cues_from_words(words: list[dict], narration: str, voice_duration: float) -> list[tuple[float, float, str]]:
    """Group word timings into readable lines, putting punctuation back from the script."""
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
        if (ends_sentence and len(text) >= 6) or (ends_clause and len(text) >= 7) or len(text) >= 24:
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


def pad_audio(src: Path, dst: Path, tail: float, voice_duration: float) -> None:
    run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"afade=t=in:st=0:d=0.008,apad=pad_dur={tail}",
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


def assemble(frame_dir: Path, audio: Path, destination: Path, fps: int, duration: float) -> None:
    fade_out = max(0.0, duration - 0.22)
    audio_filter = (
        f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
        f"afade=t=in:st=0:d=0.05,"
        f"afade=t=out:st={fade_out:.3f}:d=0.18"
    )
    run([
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", "%05d.png",
        "-i", str(audio.resolve()),
        "-filter:a", audio_filter,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-tune", "animation",
        "-crf", "18",
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
