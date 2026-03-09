from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass
from typing import Optional

import numpy as np

SAMPLE_RATE = 44_100
BEEP_DURATION_SECONDS = 0.12
STAGE_START_CUE_FREQ = 1_800.0
STAGE_START_CUE_BEEP_DURATION_SECONDS = 0.14
STAGE_START_CUE_GAP_SECONDS = 0.08
PRE_START_SECONDS = 5.0
DEFAULT_KOKORO_MODEL = "hexgrad/Kokoro-82M"
DEFAULT_KOKORO_SAMPLE_RATE = 24_000


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
    kokoro_model: str = DEFAULT_KOKORO_MODEL
    kokoro_voice: Optional[str] = None
    beep_mix_gain: float = 0.85
    voice_mix_gain: float = 1.0


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


def silence_samples(samples: int) -> np.ndarray:
    if samples <= 0:
        return np.zeros(0, dtype=np.float32)
    return np.zeros(int(samples), dtype=np.float32)


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


def _resample_audio(
    audio: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    if audio.size == 0 or source_rate <= 0 or source_rate == target_rate:
        return audio.astype(np.float32, copy=False)

    src_len = audio.shape[0]
    duration = src_len / source_rate
    target_len = max(1, int(round(duration * target_rate)))
    src_x = np.linspace(0.0, 1.0, src_len, endpoint=False)
    dst_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
    return np.interp(dst_x, src_x, audio).astype(np.float32)


def _to_mono_float_audio(audio: object) -> np.ndarray:
    arr = np.asarray(audio)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float32)

    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        max_abs = float(max(abs(info.min), info.max))
        arr = arr.astype(np.float32) / max_abs
    else:
        arr = arr.astype(np.float32, copy=False)

    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        if arr.shape[0] == 1:
            return arr[0]
        if arr.shape[1] == 1:
            return arr[:, 0]
        if arr.shape[0] <= 8 and arr.shape[1] > 8:
            return arr.mean(axis=0).astype(np.float32)
        if arr.shape[1] <= 8 and arr.shape[0] > 8:
            return arr.mean(axis=1).astype(np.float32)
        return arr.mean(axis=0).astype(np.float32)
    return arr.reshape(-1).astype(np.float32)


def _extract_audio_from_tts_output(output: object) -> tuple[np.ndarray, int]:
    sampling_rate = DEFAULT_KOKORO_SAMPLE_RATE
    payload = output

    if isinstance(payload, list):
        if not payload:
            return np.zeros(0, dtype=np.float32), sampling_rate
        payload = payload[0]

    if isinstance(payload, tuple) and len(payload) >= 2:
        maybe_rate = payload[1]
        if isinstance(maybe_rate, (int, float)) and int(maybe_rate) > 0:
            sampling_rate = int(maybe_rate)
        payload = payload[0]

    if isinstance(payload, dict):
        maybe_rate = payload.get("sampling_rate", payload.get("audio_sampling_rate"))
        if isinstance(maybe_rate, (int, float)) and int(maybe_rate) > 0:
            sampling_rate = int(maybe_rate)
        payload = payload.get(
            "audio", payload.get("waveform", np.zeros(0, dtype=np.float32))
        )

    audio = _to_mono_float_audio(payload)
    if audio.size == 0:
        return audio, sampling_rate

    peak = float(np.max(np.abs(audio)))
    if peak > 1.0:
        audio = audio / peak
    return audio.astype(np.float32), sampling_rate


def _decode_wav_bytes(payload: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(payload), "rb") as wf:
        source_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 1:
        audio = (
            np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0
        ) / 128.0
    elif sample_width == 4:
        audio = (
            np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2_147_483_648.0
        )
    else:
        raise RuntimeError(
            f"Unsupported WAV sample width from Kokoro output: {sample_width}"
        )

    if channels > 1 and audio.size:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio.astype(np.float32), source_rate


def _select_kokoro_voice(lang: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    lang_l = lang.lower()
    if lang_l.startswith("fr"):
        return "ff_siwis"
    return "af_heart"


def _tts_rate_to_speed(tts_rate: int) -> float:
    # Keep tts-rate semantics while mapping to Kokoro speed multiplier.
    return max(0.5, min(2.0, float(tts_rate) / 140.0))


class KokoroTransformerTTS:
    def __init__(
        self, model_id: str, lang: str, tts_rate: int, voice: Optional[str]
    ) -> None:
        self.model_id = model_id
        self.lang = lang
        self.voice = _select_kokoro_voice(lang, voice)
        self.speed = _tts_rate_to_speed(tts_rate)
        self._pipeline = None
        self._pipeline_error: Optional[Exception] = None
        self._inference_client = None

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if self._pipeline_error is not None:
            return None

        try:
            from transformers import pipeline
        except ImportError as exc:
            self._pipeline_error = exc
            return None

        try:
            self._pipeline = pipeline(
                "text-to-speech",
                model=self.model_id,
                trust_remote_code=True,
                device=-1,
            )
        except Exception as exc:
            self._pipeline_error = exc
            return None
        return self._pipeline

    def _ensure_inference_client(self):
        if self._inference_client is not None:
            return self._inference_client

        try:
            from huggingface_hub import InferenceClient
        except ImportError as exc:
            raise RuntimeError(
                "Kokoro inference transport requires huggingface_hub. "
                "Install with: pip install huggingface_hub"
            ) from exc

        self._inference_client = InferenceClient()
        return self._inference_client

    def synthesize(self, text: str) -> np.ndarray:
        if not text.strip():
            return np.zeros(0, dtype=np.float32)

        tts = self._ensure_pipeline()
        call_attempts: list[dict[str, object]] = []
        speed = self.speed

        if tts is not None:
            if self.voice:
                forward_params = {"voice": self.voice}
                if abs(speed - 1.0) > 1e-6:
                    forward_params["speed"] = speed
                call_attempts.append({"forward_params": forward_params})
                call_attempts.append({"voice": self.voice, "speed": speed})
                call_attempts.append({"voice": self.voice})

            if abs(speed - 1.0) > 1e-6:
                call_attempts.append({"forward_params": {"speed": speed}})
                call_attempts.append({"speed": speed})

            call_attempts.append({})
        last_error: Optional[Exception] = None

        for kwargs in call_attempts:
            try:
                output = tts(text, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue
            except Exception as exc:
                last_error = exc
                continue

            audio, source_rate = _extract_audio_from_tts_output(output)
            if audio.size == 0:
                continue
            return _resample_audio(audio, source_rate, SAMPLE_RATE)

        # Secondary Kokoro transport: HF Inference API.
        try:
            client = self._ensure_inference_client()
            response = client.text_to_speech(text, model=self.model_id)
            if isinstance(response, (bytes, bytearray)):
                payload = bytes(response)
            else:
                payload = b"".join(response)
            audio, source_rate = _decode_wav_bytes(payload)
            if audio.size:
                return _resample_audio(audio, source_rate, SAMPLE_RATE)
        except Exception as exc:
            last_error = exc

        message = (
            f"Kokoro-TTS synthesis failed for model '{self.model_id}'. "
            "Check selected voice/options and runtime dependencies."
        )
        if self._pipeline_error is not None:
            message += f" Local Kokoro load error: {self._pipeline_error}."
        if last_error is None:
            raise RuntimeError(message)
        raise RuntimeError(message) from last_error


def _generate_beep_block(
    *,
    speed_kmh: float,
    duration_seconds: float,
    distance_marker: float,
    beep_freq: float,
    beep_duration: float = BEEP_DURATION_SECONDS,
) -> np.ndarray:
    if duration_seconds <= 0:
        return np.zeros(0, dtype=np.float32)

    speed_mps = speed_kmh / 3.6
    marker_interval = distance_marker / speed_mps
    marker_count = int(math.floor((duration_seconds - 1e-9) / marker_interval)) + 1
    marker_beep_duration = min(
        max(0.02, beep_duration), max(0.02, marker_interval - 0.01)
    )
    marker_tone = beep(duration=marker_beep_duration, freq=beep_freq)

    total_samples = int(round(duration_seconds * SAMPLE_RATE))
    block = np.zeros(total_samples, dtype=np.float32)

    for idx in range(marker_count):
        onset_seconds = idx * marker_interval
        if onset_seconds >= duration_seconds:
            break
        start = int(round(onset_seconds * SAMPLE_RATE))
        if start >= total_samples:
            continue
        end = min(total_samples, start + marker_tone.size)
        block[start:end] = block[start:end] + marker_tone[: end - start]

    return block


def _generate_beep_block_with_phase(
    *,
    speed_kmh: float,
    duration_seconds: float,
    distance_marker: float,
    beep_freq: float,
    distance_to_next_marker: float,
    beep_duration: float = BEEP_DURATION_SECONDS,
) -> tuple[np.ndarray, float, list[int]]:
    if duration_seconds <= 0:
        return np.zeros(0, dtype=np.float32), distance_to_next_marker, []

    speed_mps = speed_kmh / 3.6
    if speed_mps <= 0:
        return np.zeros(int(round(duration_seconds * SAMPLE_RATE)), dtype=np.float32), distance_to_next_marker, []

    marker_beep_duration = min(
        max(0.02, beep_duration), max(0.02, (distance_marker / speed_mps) - 0.01)
    )
    marker_tone = beep(duration=marker_beep_duration, freq=beep_freq)

    total_samples = int(round(duration_seconds * SAMPLE_RATE))
    block = np.zeros(total_samples, dtype=np.float32)
    marker_offsets: list[int] = []

    t = 0.0
    dist_to_next = float(distance_to_next_marker)
    if dist_to_next < 0:
        dist_to_next = 0.0
    eps = 1e-9

    while t < duration_seconds - eps:
        if dist_to_next <= eps:
            start = int(round(t * SAMPLE_RATE))
            if start < total_samples:
                end = min(total_samples, start + marker_tone.size)
                block[start:end] = block[start:end] + marker_tone[: end - start]
                marker_offsets.append(start)
            dist_to_next = distance_marker
            continue

        dt = dist_to_next / speed_mps
        remaining = duration_seconds - t
        if dt >= remaining - eps:
            dist_to_next = max(0.0, dist_to_next - (speed_mps * remaining))
            t = duration_seconds
            break

        t += dt
        dist_to_next = 0.0

    return block, dist_to_next, marker_offsets


def _generate_stage_start_cue() -> np.ndarray:
    return np.concatenate(
        [
            beep(
                duration=STAGE_START_CUE_BEEP_DURATION_SECONDS,
                freq=STAGE_START_CUE_FREQ,
            ),
            silence(STAGE_START_CUE_GAP_SECONDS),
            beep(
                duration=STAGE_START_CUE_BEEP_DURATION_SECONDS,
                freq=STAGE_START_CUE_FREQ,
            ),
        ]
    ).astype(np.float32)


def _trim_silence(audio: np.ndarray, threshold: float = 0.02) -> np.ndarray:
    if audio.size == 0:
        return audio
    active = np.flatnonzero(np.abs(audio) > threshold)
    if active.size == 0:
        return audio
    return audio[active[0] : active[-1] + 1]


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


def _place_signal(base: np.ndarray, signal: np.ndarray, start_sample: int) -> None:
    if base.size == 0 or signal.size == 0:
        return

    src_offset = 0
    start = start_sample
    if start < 0:
        src_offset = -start
        start = 0
    if start >= base.size:
        return
    if src_offset >= signal.size:
        return

    available = min(base.size - start, signal.size - src_offset)
    if available <= 0:
        return
    end = start + available

    base[start:end] = base[start:end] + signal[src_offset : src_offset + (end - start)]


def mix_tracks(
    beep_track: np.ndarray,
    voice_track: np.ndarray,
    beep_scale: float = 0.85,
    voice_scale: float = 1.0,
) -> np.ndarray:
    if beep_track.size == 0 and voice_track.size == 0:
        return np.zeros(0, dtype=np.float32)

    length = max(beep_track.size, voice_track.size)
    mixed = np.zeros(length, dtype=np.float32)
    if beep_track.size:
        mixed[: beep_track.size] = mixed[: beep_track.size] + (beep_track * beep_scale)
    if voice_track.size:
        mixed[: voice_track.size] = mixed[: voice_track.size] + (
            voice_track * voice_scale
        )
    return mixed


def _format_number(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _validate_config(config: VamevalConfig) -> None:
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
    if config.beep_mix_gain < 0:
        raise ValueError("beep_mix_gain must be >= 0")
    if config.voice_mix_gain < 0:
        raise ValueError("voice_mix_gain must be >= 0")
    if "kokoro" not in config.kokoro_model.lower():
        raise ValueError(
            "kokoro_model must reference a Kokoro-TTS model (for example: hexgrad/Kokoro-82M)"
        )


def generate_vameval_tracks(
    config: VamevalConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _validate_config(config)
    tts_backend: Optional[KokoroTransformerTTS] = None
    if config.announce:
        tts_backend = KokoroTransformerTTS(
            model_id=config.kokoro_model,
            lang=config.lang,
            tts_rate=config.tts_rate,
            voice=config.kokoro_voice,
        )

    voice_events: list[tuple[int, np.ndarray]] = []

    def synth_voice(text: str) -> np.ndarray:
        if tts_backend is None:
            return np.zeros(0, dtype=np.float32)
        return _trim_silence(tts_backend.synthesize(text))

    test_start_seconds = PRE_START_SECONDS
    marker_tone = beep(duration=BEEP_DURATION_SECONDS, freq=config.beep_freq)
    stage_cue = _generate_stage_start_cue()

    timeline: list[tuple[str, int, float, float, float]] = []
    current_time = test_start_seconds

    if config.warmup_seconds > 0:
        if config.verbose:
            print(
                f"Warmup - {config.start_speed:.1f} kilometers per hour for {config.warmup_seconds:.0f} seconds"
            )
        timeline.append(
            (
                "warmup",
                0,
                config.start_speed,
                current_time,
                current_time + config.warmup_seconds,
            )
        )
        current_time += config.warmup_seconds
        speed = config.start_speed + config.increment
    else:
        speed = config.start_speed

    stage = 1
    while speed <= config.vma_max + 1e-9:
        if config.verbose:
            print(f"Stage {stage} - {speed:.1f} km/h")
        timeline.append(("stage", stage, speed, current_time, current_time + config.stage_seconds))
        current_time += config.stage_seconds
        speed += config.increment
        stage += 1

    total_samples = int(round(current_time * SAMPLE_RATE))
    if total_samples <= 0:
        raise RuntimeError("No audio generated with the provided configuration.")
    beep_track = np.zeros(total_samples, dtype=np.float32)

    def _place_signal_seconds(
        track: np.ndarray, signal: np.ndarray, when_seconds: float, signal_scale: float = 1.0
    ) -> None:
        signal_to_place = signal if abs(signal_scale - 1.0) < 1e-9 else signal * signal_scale
        _place_signal(track, signal_to_place, int(round(when_seconds * SAMPLE_RATE)))

    # Countdown voice is anchored to the fixed pre-start window.
    if config.announce:
        countdown_text = "4, 3, 2, 1, go!"
        countdown_voice = synth_voice(countdown_text)
        countdown_start = int(round(test_start_seconds * SAMPLE_RATE)) - countdown_voice.size
        voice_events.append((countdown_start, countdown_voice))

        if config.warmup_seconds > 0:
            start_speed_str = _format_number(config.start_speed)
            warmup_seconds_str = _format_number(config.warmup_seconds)
            intro = (
                f"Warmup - {start_speed_str} kilometers per hour for {warmup_seconds_str} seconds."
            )
            intro_voice = synth_voice(intro)
            intro_gap = int(0.12 * SAMPLE_RATE)
            intro_start = countdown_start - intro_gap - intro_voice.size
            voice_events.append((intro_start, intro_voice))

    # First marker beep at test start.
    _last_beep_time = test_start_seconds
    _place_signal_seconds(beep_track, marker_tone, _last_beep_time)
    distance_to_next_marker = config.distance_marker

    # Marker beeps stay physically continuous across speed changes by carrying
    # the remaining distance to the next marker from one segment to the next.
    for segment_kind, stage_number, speed_kmh, _segment_start, segment_end in timeline:
        segment_duration = segment_end - _segment_start
        first_marker_time: Optional[float] = None

        (
            block,
            distance_to_next_marker,
            marker_offsets,
        ) = _generate_beep_block_with_phase(
            speed_kmh=speed_kmh,
            duration_seconds=segment_duration,
            distance_marker=config.distance_marker,
            beep_freq=config.beep_freq,
            distance_to_next_marker=distance_to_next_marker,
            beep_duration=BEEP_DURATION_SECONDS,
        )

        segment_start_sample = int(round(_segment_start * SAMPLE_RATE))
        _place_signal(beep_track, block, segment_start_sample)

        if marker_offsets:
            _last_beep_time = _segment_start + (marker_offsets[-1] / SAMPLE_RATE)
            if segment_kind == "stage":
                first_marker_time = _segment_start + (marker_offsets[0] / SAMPLE_RATE)

        if segment_kind == "stage" and first_marker_time is not None:
            _place_signal_seconds(beep_track, stage_cue, first_marker_time, signal_scale=1.35)
            if config.announce:
                start_text = f"starting stage {stage_number}"
                start_voice = synth_voice(start_text)
                voice_start = int(
                    round(
                        (first_marker_time + (stage_cue.size / SAMPLE_RATE) + 0.03)
                        * SAMPLE_RATE
                    )
                )
                voice_events.append((voice_start, start_voice))

    voice_track = np.zeros(beep_track.size, dtype=np.float32)

    for start_sample, voice in voice_events:
        _place_signal(voice_track, _trim_silence(voice), start_sample)

    mixed_track = mix_tracks(
        beep_track,
        voice_track,
        beep_scale=config.beep_mix_gain,
        voice_scale=config.voice_mix_gain,
    )
    return beep_track, voice_track, mixed_track


def generate_vameval_audio(config: VamevalConfig) -> np.ndarray:
    _, _, mixed_track = generate_vameval_tracks(config)
    return mixed_track
