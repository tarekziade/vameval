from __future__ import annotations

import argparse

from .generator import VamevalConfig, generate_vameval_tracks, save_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vameval-audio",
        description="Generate a WAV file for VAMEVAL running test audio pacing.",
    )
    parser.add_argument("--output", default="vameval.wav", help="Output WAV path.")
    parser.add_argument(
        "--beep-output",
        default=None,
        help="Optional WAV path for beep-only track.",
    )
    parser.add_argument(
        "--voice-output",
        default=None,
        help="Optional WAV path for voice-only track.",
    )
    parser.add_argument("--vma-max", type=float, default=20.0, help="Maximum speed in km/h.")
    parser.add_argument("--start-speed", type=float, default=8.5, help="Starting speed in km/h.")
    parser.add_argument("--increment", type=float, default=0.5, help="Speed increment per stage (km/h).")
    parser.add_argument("--distance", type=float, default=20.0, help="Marker distance in meters.")
    parser.add_argument("--stage-seconds", type=float, default=60.0, help="Duration of a stage in seconds.")
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.0,
        help="Warm-up duration at start speed before increments (seconds).",
    )
    parser.add_argument("--beep-freq", type=float, default=1000.0, help="Beep frequency in Hz.")
    parser.add_argument("--tts", action="store_true", help="Enable spoken stage announcements.")
    parser.add_argument("--lang", default="fr", help="Announcement language hint (e.g. fr, en).")
    parser.add_argument("--tts-rate", type=int, default=140, help="Speech rate for TTS (words/min).")
    parser.add_argument(
        "--kokoro-model",
        default="hexgrad/Kokoro-82M",
        help="Kokoro model id (Kokoro-only generation path).",
    )
    parser.add_argument(
        "--kokoro-voice",
        default=None,
        help="Optional Kokoro voice preset override.",
    )
    parser.add_argument(
        "--beep-mix-gain",
        type=float,
        default=0.85,
        help="Beep gain used when creating the final mix.",
    )
    parser.add_argument(
        "--voice-mix-gain",
        type=float,
        default=1.0,
        help="Voice gain used when creating the final mix.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print stage progression.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = VamevalConfig(
        vma_max=args.vma_max,
        start_speed=args.start_speed,
        increment=args.increment,
        distance_marker=args.distance,
        announce=args.tts,
        lang=args.lang,
        verbose=args.verbose,
        beep_freq=args.beep_freq,
        stage_seconds=args.stage_seconds,
        warmup_seconds=args.warmup_seconds,
        tts_rate=args.tts_rate,
        kokoro_model=args.kokoro_model,
        kokoro_voice=args.kokoro_voice,
        beep_mix_gain=args.beep_mix_gain,
        voice_mix_gain=args.voice_mix_gain,
    )

    beep_track, voice_track, mixed_track = generate_vameval_tracks(config)
    save_wav(args.output, mixed_track)
    print(f"Generated mix: {args.output}")

    if args.beep_output:
        save_wav(args.beep_output, beep_track)
        print(f"Generated beeps: {args.beep_output}")

    if args.voice_output:
        save_wav(args.voice_output, voice_track)
        print(f"Generated voice: {args.voice_output}")


if __name__ == "__main__":
    main()
