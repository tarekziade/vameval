from __future__ import annotations

import math
import os
import shutil
import tempfile
import time
import wave
import aifc
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np

SAMPLE_RATE = 44_100
BEEP_DURATION_SECONDS = 0.12
STAGE_START_CUE_FREQ = 1_800.0
STAGE_START_CUE_DURATION_SECONDS = 0.42


@dataclass(frozen=True)
class VamevalConfig:
    vma_max: float = 20.0
    start_speed: float = 8.5
    increment: float = 0.5
    distance_marker: float = 20.0
    announce: bool = False
    lang: str = "fr"
    verbose: bool = False
    beep_freq: float = 1_000.0
    stage_seconds: float = 60.0
    warmup_seconds: float = 0.0
    tts_rate: int = 140


def beep(duration: float = BEEP_DURATION_SECONDS, freq: float = 1_000.0) -> np.ndarray:
    t = np.linspace(
        0.0, duration, int(SAMPLE_RATE * duration), endpoint=False, dtype=np.float32
    )
    tone = np.sin(freq * 2.0 * np.pi * t).astype(np.float32)
    envelope = np.linspace(1.0, 0.2, len(t), dtype=np.float32)
    return tone * envelope


def silence(duration: float) -> np.ndarray:
    if duration <= 0:
        return np.zeros(0, dtype=np.float32)
    return np.zeros(int(SAMPLE_RATE * duration), dtype=np.float32)


def save_wav(filename: str, data: np.ndarray) -> None:
    if data.size == 0:
        raise ValueError("Audio buffer is empty. Nothing to save.")

    peak = float(np.max(np.abs(data)))
    if peak == 0:
        scaled = np.zeros_like(data, dtype=np.int16)
    else:
        scaled = np.int16((data / peak) * 32767)

    with wave.open(filename, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(scaled.tobytes())


def _get_tts_engine(tts_rate: int):
    try:
        import pyttsx3
    except ImportError as exc:
        raise RuntimeError(
            "TTS requested but pyttsx3 is not installed. Install with: pip install .[tts]"
        ) from exc

    engine = pyttsx3.init()
    engine.setProperty("rate", int(tts_rate))
    return engine


def _select_voice(engine, lang: str) -> None:
    lang_l = lang.lower()
    for voice in engine.getProperty("voices"):
        name = getattr(voice, "name", "").lower()
        voice_id = getattr(voice, "id", "").lower()
        langs = []
        for raw_lang in getattr(voice, "languages", []):
            if isinstance(raw_lang, bytes):
                langs.append(raw_lang.decode(errors="ignore").lower())
            else:
                langs.append(str(raw_lang).lower())

        if lang_l in name or lang_l in voice_id or any(lang_l in l for l in langs):
            engine.setProperty("voice", voice.id)
            return


def text_to_speech(
    text: str, engine, lang: str = "fr", tts_rate: int = 140
) -> np.ndarray:
    # On macOS, pyttsx3 often drops queued save_to_file utterances after the first.
    if sys.platform == "darwin" and shutil.which("say"):
        audio = _text_to_speech_say(text, lang, tts_rate)
        if audio.size:
            return audio

    audio = _text_to_speech_engine(text, engine)
    if audio.size:
        return audio

    # Safety fallback if engine output is empty.
    if shutil.which("say"):
        return _text_to_speech_say(text, lang, tts_rate)
    return audio


def _decode_audio_file(path: str) -> np.ndarray:
    source_rate: int
    channels: int
    sample_width: int
    byte_order: str
    frames: bytes
    converted_path = f"{path}.converted.wav"
    try:
        try:
            with wave.open(path, "rb") as wf:
                source_rate = wf.getframerate()
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                frames = wf.readframes(wf.getnframes())
                byte_order = "little"
        except wave.Error:
            try:
                with aifc.open(path, "rb") as af:
                    source_rate = af.getframerate()
                    channels = af.getnchannels()
                    sample_width = af.getsampwidth()
                    frames = af.readframes(af.getnframes())
                    byte_order = "big"
            except aifc.Error:
                # macOS voices may emit compressed AIFF; convert to PCM WAV.
                subprocess.run(
                    [
                        "afconvert",
                        "-f",
                        "WAVE",
                        "-d",
                        "LEI16@44100",
                        path,
                        converted_path,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with wave.open(converted_path, "rb") as wf:
                    source_rate = wf.getframerate()
                    channels = wf.getnchannels()
                    sample_width = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())
                    byte_order = "little"

        if sample_width == 2:
            dtype = np.dtype("<i2" if byte_order == "little" else ">i2")
            audio = np.frombuffer(frames, dtype=dtype).astype(np.float32)
        elif sample_width == 1:
            dtype = np.dtype("u1" if byte_order == "little" else "i1")
            audio = np.frombuffer(frames, dtype=dtype).astype(np.float32)
            if byte_order == "little":
                audio -= 128.0
        elif sample_width == 4:
            dtype = np.dtype("<i4" if byte_order == "little" else ">i4")
            audio = np.frombuffer(frames, dtype=dtype).astype(np.float32) / 65536.0
        else:
            return np.zeros(0, dtype=np.float32)

        if channels > 1 and audio.size:
            audio = audio.reshape(-1, channels).mean(axis=1)

        if source_rate != SAMPLE_RATE and audio.size:
            src_len = audio.shape[0]
            duration = src_len / source_rate
            target_len = max(1, int(round(duration * SAMPLE_RATE)))
            src_x = np.linspace(0.0, 1.0, src_len, endpoint=False)
            dst_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
            audio = np.interp(dst_x, src_x, audio).astype(np.float32)

        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / peak
        return audio
    finally:
        if os.path.exists(converted_path):
            os.remove(converted_path)


def _text_to_speech_engine(text: str, engine) -> np.ndarray:
    fd, path = tempfile.mkstemp(suffix=".aiff")
    os.close(fd)
    try:
        engine.save_to_file(text, path)
        engine.runAndWait()

        # Wait for file output completion.
        for _ in range(60):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                break
            time.sleep(0.05)
        return _decode_audio_file(path)
    finally:
        if os.path.exists(path):
            os.remove(path)


def _text_to_speech_say(text: str, lang: str, tts_rate: int) -> np.ndarray:
    fd, path = tempfile.mkstemp(suffix=".aiff")
    os.close(fd)

    voice = None
    lang_l = lang.lower()
    if lang_l.startswith("fr"):
        voice = "Thomas"
    elif lang_l.startswith("en"):
        voice = "Alex"

    try:
        if voice:
            cmd = ["say", "-v", voice, "-r", str(int(tts_rate)), "-o", path, text]
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if proc.returncode != 0:
                cmd = ["say", "-r", str(int(tts_rate)), "-o", path, text]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            cmd = ["say", "-r", str(int(tts_rate)), "-o", path, text]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return _decode_audio_file(path)
    finally:
        if os.path.exists(path):
            os.remove(path)


def _generate_beep_block(
    *,
    speed_kmh: float,
    duration_seconds: float,
    distance_marker: float,
    beep_freq: float,
    beep_duration: float = BEEP_DURATION_SECONDS,
) -> np.ndarray:
    speed_mps = speed_kmh / 3.6
    marker_interval = distance_marker / speed_mps
    marker_count = int(math.floor(duration_seconds / marker_interval))
    elapsed = 0.0
    parts: list[np.ndarray] = []
    marker_beep_duration = min(max(0.02, beep_duration), max(0.02, marker_interval - 0.01))

    for _ in range(marker_count):
        parts.append(beep(duration=marker_beep_duration, freq=beep_freq))
        parts.append(silence(marker_interval - marker_beep_duration))
        elapsed += marker_interval

    parts.append(silence(duration_seconds - elapsed))
    return np.concatenate(parts).astype(np.float32)


def _trim_silence(audio: np.ndarray, threshold: float = 0.02) -> np.ndarray:
    if audio.size == 0:
        return audio
    active = np.flatnonzero(np.abs(audio) > threshold)
    if active.size == 0:
        return audio
    return audio[active[0] : active[-1] + 1]


def _overlay_voice(
    base: np.ndarray,
    voice: np.ndarray,
    start_sample: int,
    segment_scale: float = 0.85,
    speech_scale: float = 1.0,
) -> np.ndarray:
    voice = _trim_silence(voice)
    if base.size == 0 or voice.size == 0:
        return base

    start = max(0, start_sample)
    end = min(base.size, start + voice.size)
    if end <= start:
        return base

    mixed = base.copy()
    segment = mixed[start:end]
    speech = voice[: end - start]
    # Default behavior mutes underlying beeps during speech for clear intelligibility.
    mixed[start:end] = (segment * segment_scale) + (speech * speech_scale)
    return mixed


def _mix_signal(
    base: np.ndarray, signal: np.ndarray, start_sample: int, signal_scale: float = 1.0
) -> np.ndarray:
    if base.size == 0 or signal.size == 0:
        return base

    start = max(0, start_sample)
    end = min(base.size, start + signal.size)
    if end <= start:
        return base

    mixed = base.copy()
    mixed[start:end] = mixed[start:end] + (signal[: end - start] * signal_scale)
    return mixed


def _append_beep_block(
    chunks: list[np.ndarray],
    *,
    speed_kmh: float,
    duration_seconds: float,
    distance_marker: float,
    beep_freq: float,
    beep_duration: float = BEEP_DURATION_SECONDS,
) -> None:
    chunks.append(
        _generate_beep_block(
            speed_kmh=speed_kmh,
            duration_seconds=duration_seconds,
            distance_marker=distance_marker,
            beep_freq=beep_freq,
            beep_duration=beep_duration,
        )
    )


def _format_number(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def generate_vameval_audio(config: VamevalConfig) -> np.ndarray:
    if config.start_speed <= 0:
        raise ValueError("start_speed must be > 0")
    if config.increment <= 0:
        raise ValueError("increment must be > 0")
    if config.distance_marker <= 0:
        raise ValueError("distance_marker must be > 0")
    if config.stage_seconds <= 0:
        raise ValueError("stage_seconds must be > 0")
    if config.warmup_seconds < 0:
        raise ValueError("warmup_seconds must be >= 0")
    if config.tts_rate <= 0:
        raise ValueError("tts_rate must be > 0")
    if config.vma_max < config.start_speed:
        raise ValueError("vma_max must be >= start_speed")

    engine: Optional[object] = None
    is_french = config.lang.lower().startswith("fr")
    if config.announce:
        engine = _get_tts_engine(config.tts_rate)
        _select_voice(engine, config.lang)

    chunks: list[np.ndarray] = []

    # Optional warm-up at start speed, then stage 1 starts at +increment.
    if config.warmup_seconds > 0:
        if config.verbose:
            print(
                f"Warmup - {config.start_speed:.1f} km/h for {config.warmup_seconds:.0f}s"
            )

        warmup_block = _generate_beep_block(
            speed_kmh=config.start_speed,
            duration_seconds=config.warmup_seconds,
            distance_marker=config.distance_marker,
            beep_freq=config.beep_freq,
        )

        if config.announce and engine is not None:
            warmup_minutes = config.warmup_seconds / 60.0
            minutes_str = _format_number(warmup_minutes)
            start_speed_str = _format_number(config.start_speed)
            if is_french:
                intro = (
                    f"Echauffement {minutes_str} minutes. "
                    f"{start_speed_str} kilometres heure."
                )
            else:
                intro = (
                    f"Warmup {minutes_str} minutes. "
                    f"{start_speed_str} kilometers per hour."
                )

            intro_voice = text_to_speech(intro, engine, config.lang, config.tts_rate)
            # Intro is before the timed warmup block.
            chunks.append(intro_voice)
            chunks.append(silence(0.25))

            # For a 2-minute warm-up, inject "Encore une minute" at midpoint.
            if abs(config.warmup_seconds - 120.0) < 1:
                mid_text = "Encore une minute" if is_french else "One minute remaining"
                mid_voice = text_to_speech(mid_text, engine, config.lang, config.tts_rate)
                midpoint = warmup_block.size // 2
                warmup_block = _overlay_voice(
                    warmup_block, mid_voice, midpoint - (mid_voice.size // 2)
                )

            # Countdown is overlaid at the end so stage 1 can start exactly at warmup end.
            if is_french:
                countdown_text = "4, 3, 2, 1, Partez!"
            else:
                countdown_text = "4, 3, 2, 1, Go!"
            countdown_voice = text_to_speech(
                countdown_text, engine, config.lang, config.tts_rate
            )
            warmup_block = _overlay_voice(
                warmup_block,
                countdown_voice,
                warmup_block.size - countdown_voice.size - int(0.10 * SAMPLE_RATE),
            )

        chunks.append(warmup_block)
        speed = config.start_speed + config.increment
    else:
        speed = config.start_speed
        if config.announce and engine is not None:
            if is_french:
                countdown_text = "4, 3, 2, 1, Partez!"
            else:
                countdown_text = "4, 3, 2, 1, Go!"
            chunks.append(text_to_speech(countdown_text, engine, config.lang, config.tts_rate))
            chunks.append(silence(0.1))

    stage = 1

    while speed <= config.vma_max + 1e-9:
        if config.verbose:
            print(f"Stage {stage} - {speed:.1f} km/h")

        stage_block = _generate_beep_block(
            speed_kmh=speed,
            duration_seconds=config.stage_seconds,
            distance_marker=config.distance_marker,
            beep_freq=config.beep_freq,
            beep_duration=BEEP_DURATION_SECONDS,
        )
        stage_cue = beep(duration=STAGE_START_CUE_DURATION_SECONDS, freq=STAGE_START_CUE_FREQ)
        stage_block = _mix_signal(stage_block, stage_cue, 0, signal_scale=1.35)

        if config.announce and engine is not None:
            speed_str = _format_number(speed)
            if is_french:
                start_text = f"Palier {stage}. {speed_str} kilometres heure"
            else:
                start_text = f"Stage {stage}. {speed_str} kilometers per hour"

            start_voice = text_to_speech(start_text, engine, config.lang, config.tts_rate)
            # Keep the start cue audible, then announce the stage.
            stage_block = _overlay_voice(
                stage_block,
                start_voice,
                int((STAGE_START_CUE_DURATION_SECONDS + 0.05) * SAMPLE_RATE),
            )

        chunks.append(stage_block)

        speed += config.increment
        stage += 1

    if not chunks:
        raise RuntimeError("No audio generated with the provided configuration.")

    return np.concatenate(chunks).astype(np.float32)
