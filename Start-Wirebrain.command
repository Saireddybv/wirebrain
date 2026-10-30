#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
python3 start_wirebrain.py
read -r -p "Press Enter to close this window."
