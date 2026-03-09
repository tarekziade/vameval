# vameval-audio

Generate a WAV sound track for a VAMEVAL running test.

## What it does

- Emits periodic beeps for each distance marker.
- Increases speed by stage.
- Optionally adds spoken announcements (`--tts` with Kokoro-TTS via Transformers).
- Builds three tracks: `beeps` (timing), `voice` (announcements), then a mixed output.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

With speech announcements (Kokoro + Transformers):

```bash
pip install -e '.[tts]'
```

## Usage

```bash
vameval-audio --output vameval.wav --vma-max 20 --start-speed 8 --increment 0.5 --distance 20 --warmup-seconds 120 --stage-seconds 60
```

Enable announcements:

```bash
vameval-audio --tts --lang fr --tts-rate 130 --beep-output beeps.wav --voice-output voice.wav --verbose
```

## Makefile workflow

```bash
make install
make run
```

With speech:

```bash
make install-tts
make run-tts
```

Note: Generation is Kokoro-only. The app uses the configured Kokoro model and can run it via local runtime or Hugging Face Inference transport depending on environment capabilities.

## VAMEVAL Protocol (Default Preset)

- Track length: `400 m`
- Marker spacing: `20 m` (beep at each marker)
- Warm-up: `2 min` at `8.0 km/h`
- Then: `+0.5 km/h` every `1 min`
- Maximum speed: `20.0 km/h`
- Spoken announcements: enabled in `make run-tts` (Kokoro-TTS)
- Before timed warmup starts: `Warmup - 8km/h for 120s.` then `4, 3, 2, 1, go!`
- At each stage boundary: one high-pitch double-beep cue
- Right after the stage cue: voice says `starting stage X`
- Marker beep remains regular inside each stage

Default outputs from `make run-tts`:

- Mixed track: `vameval_400m_tts.wav`
- Beep track: `vameval_400m_beeps.wav`
- Voice track: `vameval_400m_voice.wav`

## Result Table (Stopwatch)

This table matches the default preset in this repo (`2:00` warmup, then `1:00` per stage).

| Elapsed time | Stage reached | Speed (km/h) |
| --- | --- | --- |
| 02:00 | End warmup | 8.0 |
| 03:00 | Palier 1 | 8.5 |
| 04:00 | Palier 2 | 9.0 |
| 05:00 | Palier 3 | 9.5 |
| 06:00 | Palier 4 | 10.0 |
| 07:00 | Palier 5 | 10.5 |
| 08:00 | Palier 6 | 11.0 |
| 09:00 | Palier 7 | 11.5 |
| 10:00 | Palier 8 | 12.0 |
| 11:00 | Palier 9 | 12.5 |
| 12:00 | Palier 10 | 13.0 |
| 13:00 | Palier 11 | 13.5 |
| 14:00 | Palier 12 | 14.0 |
| 15:00 | Palier 13 | 14.5 |
| 16:00 | Palier 14 | 15.0 |
| 17:00 | Palier 15 | 15.5 |
| 18:00 | Palier 16 | 16.0 |
| 19:00 | Palier 17 | 16.5 |
| 20:00 | Palier 18 | 17.0 |
| 21:00 | Palier 19 | 17.5 |
| 22:00 | Palier 20 | 18.0 |
| 23:00 | Palier 21 | 18.5 |
| 24:00 | Palier 22 | 19.0 |
| 25:00 | Palier 23 | 19.5 |
| 26:00 | Palier 24 | 20.0 |

If the athlete stops during a stage, use the current stage speed as the result baseline.

## Options

- `--output`: output WAV path (default: `vameval_400m_tts.wav` in Makefile, `vameval.wav` in CLI)
- `--beep-output`: optional output WAV path for beep-only track
- `--voice-output`: optional output WAV path for voice-only track
- `--vma-max`: max speed in km/h
- `--start-speed`: starting speed in km/h
- `--increment`: speed increment per stage (km/h)
- `--distance`: distance marker in meters (default: 20)
- `--stage-seconds`: stage duration in seconds (default: 60)
- `--warmup-seconds`: warm-up duration at start speed before increments
- `--beep-freq`: beep frequency in Hz (default: 1000)
- `--tts`: add spoken announcements
- `--lang`: language hint for voice selection (`fr`, `en`, ...)
- `--tts-rate`: speech-rate hint mapped to Kokoro speed (default: 140 in CLI, 130 in Makefile)
- `--kokoro-model`: Transformers model id (default: `hexgrad/Kokoro-82M`)
- `--kokoro-voice`: optional Kokoro voice preset override
- `--beep-mix-gain`: beep gain used for final mix (default: `0.85`)
- `--voice-mix-gain`: voice gain used for final mix (default: `1.0`)
- `--verbose`: print stage progress

## Legacy script style

You can also run:

```bash
python -m vameval_audio.cli --output vameval.wav
```

## Author

Tarek Ziadé <tarek@ziade.org>
