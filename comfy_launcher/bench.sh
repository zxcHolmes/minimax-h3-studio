#!/usr/bin/env bash
# Usage: bench.sh <name> <run_h3.py args...>
# Runs run_h3.py while sampling GPU memory once per second with nvidia-smi.
# Run it inside the ComfyUI Python env with H3_COMFYUI set (or pass --comfyui).
set -u
name=$1; shift
cd "$(dirname "$0")"
# One GPU job at a time across all queues.
exec 9>gpu.lock
flock 9
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -lms 1000 > "$name.vram" &
smi=$!
python run_h3.py --output-dir "out_$name" "$@" > "$name.log" 2>&1
status=$?
kill $smi
echo "[bench] $name exit=$status peak_vram_MiB=$(sort -n "$name.vram" | tail -1)" | tee -a "$name.log"
