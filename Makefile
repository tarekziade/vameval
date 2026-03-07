PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
TRACK_METERS ?= 400
OUTPUT ?= vameval_$(TRACK_METERS)m_tts.wav
DISTANCE ?= 20
START_SPEED ?= 8.0
VMA_MAX ?= 20.0
INCREMENT ?= 0.5
STAGE_SECONDS ?= 60
WARMUP_SECONDS ?= 120
TTS_LANG ?= fr
TTS_RATE ?= 130

.PHONY: help venv install install-tts run run-tts clean

help:
	@echo "Targets:"
	@echo "  make venv         Create virtualenv in .venv"
	@echo "  make install      Install project (editable)"
	@echo "  make install-tts  Install project with TTS extras"
	@echo "  make run          Generate WAV with default VAMEVAL profile (no TTS)"
	@echo "  make run-tts      Generate WAV with default VAMEVAL profile + speech"
	@echo "  make clean        Remove generated WAV files"
	@echo ""
	@echo "Install once before running: make install (or make install-tts for speech)"
	@echo ""
	@echo "Defaults: 400m track, 20m markers, 8km/h start, 2min warmup, countdown, +0.5km/h per minute up to 20km/h"
	@echo "Speech defaults: French with slower voice (TTS_RATE=$(TTS_RATE))"
	@echo "Custom output: make run-tts OUTPUT=my_test.wav"

venv:
	test -d $(VENV_DIR) || $(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(VENV_PIP) install -e .

install-tts: venv
	$(VENV_PIP) install -e '.[tts]'

run: venv
	PYTHONPATH=src $(VENV_PYTHON) -m vameval_audio.cli \
		--output $(OUTPUT) \
		--vma-max $(VMA_MAX) \
		--start-speed $(START_SPEED) \
		--increment $(INCREMENT) \
		--distance $(DISTANCE) \
		--stage-seconds $(STAGE_SECONDS) \
		--warmup-seconds $(WARMUP_SECONDS)

run-tts: venv
	PYTHONPATH=src $(VENV_PYTHON) -m vameval_audio.cli \
		--output $(OUTPUT) \
		--vma-max $(VMA_MAX) \
		--start-speed $(START_SPEED) \
		--increment $(INCREMENT) \
		--distance $(DISTANCE) \
		--stage-seconds $(STAGE_SECONDS) \
		--warmup-seconds $(WARMUP_SECONDS) \
		--tts --lang $(TTS_LANG) --tts-rate $(TTS_RATE) --verbose

clean:
	rm -f ./*.wav
