#!/usr/bin/env bash
# Fetch the openly licensed demo footage (not redistributed in this repo). See ATTRIBUTION.md.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/videos
UA="TRACE-demo/0.1 (github.com/AlenHsiaoWeiLun/trace-ugen)"
wm() { curl -sfL -A "$UA" -o "data/videos/$1" "$2"; }
px() { curl -sfL -A "Mozilla/5.0" -o "data/videos/pexels_$1.mp4" "https://www.pexels.com/download/video/$1/"; }
wm bridge_06.webm "https://upload.wikimedia.org/wikipedia/commons/a/a1/June_2023_motorcycle_waterfall_on_Taipei_Bridge_by_rush_hour_commuters_06.webm"
wm bridge_07.webm "https://upload.wikimedia.org/wikipedia/commons/e/ee/June_2023_motorcycle_waterfall_on_Taipei_Bridge_by_rush_hour_commuters_07.webm"
for id in 37737804 34647618 35767994 25786069 4740223; do px "$id"; done
ls -la data/videos
