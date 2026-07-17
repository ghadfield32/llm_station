# life-center-infra — Makefile mirror of the `lc` CLI (composite targets).
# Prefer `./lc <cmd>`; this exists for operators who reach for make first.
.PHONY: help doctor setup bootstrap up down health first-boot config backup gui

PROFILE ?= foundation

help:
	@echo "Targets: doctor setup bootstrap up down health first-boot config backup gui"
	@echo "Usage:   make up PROFILE=files    (tiers: files photos media docs productivity network smart-home vault all)"

doctor:      ; python3 lc.py doctor
setup:       ; python3 lc.py setup
bootstrap:   ; python3 lc.py bootstrap
up:          ; python3 lc.py up --profile $(PROFILE)
down:        ; python3 lc.py down --profile $(PROFILE)
health:      ; python3 lc.py health --profile $(PROFILE)
first-boot:  ; python3 lc.py first-boot
config:      ; python3 lc.py config --profile $(PROFILE)
backup:      ; python3 lc.py backup
gui:         ; python3 lc.py gui
