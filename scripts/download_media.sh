#!/usr/bin/env bash
# Fetch the openly licensed demo footage (not redistributed in this repo). See ATTRIBUTION.md.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/videos
UA="TRACE-demo/0.1 (github.com/AlenHsiaoWeiLun/trace-ugen)"
fetch() {
  local target="data/videos/$1" temp="data/videos/$1.part"
  if [[ -s "$target" ]]; then echo "Using $target"; return; fi
  echo "Downloading $target"
  if ! curl -fL --retry 2 --connect-timeout 20 --max-time 180 -A "$3" -o "$temp" "$2"; then
    rm -f "$temp"
    echo "Download failed: $2. Open the source in ATTRIBUTION.md and save its video as $target, then re-run this script." >&2
    return 1
  fi
  if [[ ! -s "$temp" ]]; then rm -f "$temp"; return 1; fi
  mv "$temp" "$target"
}
wm() { fetch "$1" "$2" "$UA"; }
px() { fetch "pexels_$1.mp4" "https://www.pexels.com/download/video/$1/" "Mozilla/5.0"; }
wm bridge_06.webm "https://upload.wikimedia.org/wikipedia/commons/a/a1/June_2023_motorcycle_waterfall_on_Taipei_Bridge_by_rush_hour_commuters_06.webm"
wm bridge_07.webm "https://upload.wikimedia.org/wikipedia/commons/e/ee/June_2023_motorcycle_waterfall_on_Taipei_Bridge_by_rush_hour_commuters_07.webm"
# TRACE metro/road replay
for id in 37737804 34647618 35767994 25786069 4740223; do px "$id"; done
# VESTIGE campus (CAM-P3/P5/W1/G2) and construction (CAM-S1/S2) workspaces
for id in 4649964 8405570 4649966 4650158 32268405 28795446; do px "$id"; done
ls -la data/videos
