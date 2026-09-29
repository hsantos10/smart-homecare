"""Transcribe a field-test voice memo with faster-whisper.

Produces a transcript JSON (segments with start/end/text) for the field-test
review notebooks, plus a .txt sidecar with one "[mm:ss] text" line per segment.

    python scripts/transcribe_audio.py "<audio.m4a>" --out notebooks/<test>_transcript.json

Runs on the GPU when ctranslate2 sees CUDA, else CPU int8. PyAV decodes the
container, so no system ffmpeg is needed. The transcript files are gitignored
(notebooks/*_transcript*.json) because they name people.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# The LLMs env ships two copies of Intel's OpenMP runtime (ctranslate2 + MKL); without this
# the process aborts with "OMP: Error #15" before transcribing anything.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def container_metadata(path: Path) -> dict:
    import av

    with av.open(str(path)) as c:
        meta = dict(c.metadata)
        meta["duration_sec"] = round(c.duration / 1e6, 2) if c.duration else None
        for s in c.streams:
            if s.type == "audio":
                meta["codec"] = s.codec_context.name
                meta.update({f"stream_{k}": v for k, v in s.metadata.items()})
                break
    return meta


def mmss(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path)
    ap.add_argument("--out", type=Path, help="JSON path (default: notebooks/<audio-stem>_transcript.json)")
    ap.add_argument("--model", default="large-v3", help="faster-whisper model (large-v3, medium.en, small.en, ...)")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--language", default="en")
    ap.add_argument("--no-vad", action="store_true", help="disable the VAD filter")
    ap.add_argument("--prompt", default="Narrated smart-home activity test: get up, closet, toilet, shower, fridge, cabinet, cook, breakfast, front door, sofa, study desk.",
                    help="initial prompt to bias vocabulary")
    args = ap.parse_args()

    if not args.audio.exists():
        print(f"audio not found: {args.audio}", file=sys.stderr)
        return 1
    out = args.out or Path("notebooks") / f"{args.audio.stem}_transcript.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel

    device = args.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    print(f"model={args.model} device={device} compute={compute}")

    t0 = time.time()
    model = WhisperModel(args.model, device=device, compute_type=compute)
    print(f"model loaded in {time.time() - t0:.1f}s")

    t1 = time.time()
    segments_iter, info = model.transcribe(
        str(args.audio),
        language=args.language,
        vad_filter=not args.no_vad,
        word_timestamps=True,
        initial_prompt=args.prompt,
        beam_size=5,
    )
    segments = []
    for seg in segments_iter:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word} for w in (seg.words or [])],
        })
        print(f"[{mmss(seg.start)}] {seg.text.strip()}")
    print(f"transcribed {len(segments)} segments in {time.time() - t1:.1f}s (audio {info.duration:.0f}s)")

    doc = {
        "source": str(args.audio),
        "duration_sec": round(info.duration, 2),
        "metadata": container_metadata(args.audio),
        "model": f"faster-whisper {args.model} ({device}/{compute})",
        "language": info.language,
        "segments": segments,
    }
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    txt = out.with_suffix(".txt")
    txt.write_text("\n".join(f"[{mmss(s['start'])}] {s['text']}" for s in segments) + "\n", encoding="utf-8")
    print(f"wrote {out}\nwrote {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
