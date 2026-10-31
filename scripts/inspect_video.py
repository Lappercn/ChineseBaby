"""Create timestamped contact sheets for local reference videos.

Requires Pillow and ffmpeg (PATH, --ffmpeg, or imageio-ffmpeg).
This samples visual evidence; it does not transcribe or analyse audio.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image, ImageDraw


def find_ffmpeg(explicit):
    if explicit:
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise SystemExit("Provide --ffmpeg or install imageio-ffmpeg.") from exc


def run(command):
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")


def inspect(source, output, ffmpeg, count, start, end):
    probe = run([ffmpeg, "-hide_banner", "-i", str(source)])
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
    if not match:
        raise RuntimeError(f"Cannot read duration: {source}\n{probe.stderr[-2000:]}")
    hours, minutes, seconds = map(float, match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    # Container/audio duration can exceed the last decodable video frame.
    safe_end = duration - min(0.25, duration * 0.1)
    stop = min(safe_end, end if end is not None else safe_end)
    if not 0 <= start < stop:
        raise ValueError("Require 0 <= start < end < duration")
    output.mkdir(parents=True, exist_ok=True)
    folder = output / source.stem
    folder.mkdir(exist_ok=True)
    times = [start + (stop - start) * i / (count - 1) for i in range(count)]
    columns = 4
    width, height = 384, 250
    sheet = Image.new("RGB", (columns * width, math.ceil(count / columns) * height), "#141414")
    draw = ImageDraw.Draw(sheet)
    frames = []
    for index, stamp in enumerate(times):
        image_path = folder / f"frame-{index:02d}.jpg"
        result = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                      "-ss", f"{stamp:.6f}", "-i", str(source),
                      "-frames:v", "1", "-vf", "scale=768:-2,format=yuvj420p", str(image_path)])
        if result.returncode or not image_path.exists():
            raise RuntimeError(f"Frame extraction failed at {stamp}: {result.stderr}")
        with Image.open(image_path) as frame:
            preview = frame.convert("RGB")
            preview.thumbnail((width - 12, height - 32))
            x = (index % columns) * width
            y = (index // columns) * height
            sheet.paste(preview, (x + (width - preview.width) // 2, y + 26))
            draw.text((x + 8, y + 7), f"{index:02d} | requested t={stamp:.3f}s", fill="white")
        frames.append({"requestedTimeSeconds": round(stamp, 6), "path": image_path.name})
    sheet_path = folder / "contact-sheet.jpg"
    sheet.save(sheet_path, quality=92)
    metadata = {"source": str(source.resolve()), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "durationSeconds": duration, "sampleCount": count,
                "rangeSeconds": [start, stop], "frames": frames,
                "contactSheet": sheet_path.name,
                "samplingLimit": "Requested seek times; frame time can differ by one frame. Last 250ms excluded to avoid audio/container tails. No audio analysis.",
                "probe": probe.stderr}
    (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": source.name, "duration": duration, "sheet": str(sheet_path)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    args = parser.parse_args()
    if not 2 <= args.count <= 64:
        parser.error("--count must be between 2 and 64")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    for video in args.videos:
        inspect(video.resolve(strict=True), args.out.resolve(), ffmpeg, args.count, args.start, args.end)


if __name__ == "__main__":
    main()
