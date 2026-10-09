"""Convert downloaded WebVTT to clean, timestamped SRT, TXT and JSON."""

import html
import json
import re
from pathlib import Path

TIMING = re.compile(r"^((?:\d+:)?\d{2}:\d{2}\.\d{3})\s+-->\s+((?:\d+:)?\d{2}:\d{2}\.\d{3})")


def seconds(value):
    parts = value.split(":")
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def timestamp(value, separator="."):
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{ms:03}"


def parse_vtt(text, deduplicate=False):
    cues = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    previous = ""
    while index < len(lines):
        match = TIMING.match(lines[index])
        index += 1
        if not match:
            continue
        body = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        clean = html.unescape(re.sub(r"<[^>]*>", "", " ".join(body)))
        clean = " ".join(clean.split())
        start, end = seconds(match[1]), seconds(match[2])
        # YouTube automatic captions repeat the previous line in rolling windows.
        # Remove only prefix overlap with the immediately preceding raw cue.
        words, old = clean.split(), previous.split()
        previous = clean
        overlap = 0
        for length in range(min(len(old), len(words)), 0, -1):
            if old[-length:] == words[:length]:
                overlap = length
                break
        if deduplicate and cues and start <= cues[-1]["end"] + 0.1:
            words = words[overlap:]
        clean = " ".join(words)
        if clean and end > start:
            cues.append({"start": start, "end": end, "text": clean})
    return cues


def export_transcript(vtt: Path, deduplicate=False):
    cues = parse_vtt(vtt.read_text(encoding="utf-8-sig"), deduplicate=deduplicate)
    if not cues:
        raise ValueError("The caption track contains no readable cues.")
    base = vtt.with_suffix("")
    paths = [base.with_suffix(base.suffix + extension) for extension in (".srt", ".txt", ".json")]
    paths[0].write_text("\n\n".join(
        f"{index}\n{timestamp(cue['start'], ',')} --> {timestamp(cue['end'], ',')}\n{cue['text']}"
        for index, cue in enumerate(cues, 1)) + "\n", encoding="utf-8")
    paths[1].write_text("\n".join(f"[{timestamp(cue['start'])}] {cue['text']}" for cue in cues) + "\n", encoding="utf-8")
    paths[2].write_text(json.dumps(cues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths
