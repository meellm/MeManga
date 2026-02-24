#!/bin/bash
cd ~/MeManga
source venv/bin/activate

echo "=== Starting MakeHero download ==="
# MakeHero is already running, skip if still going

echo "=== Starting Shikimori download (201 chapters) ==="
python3 -m memanga check -t "Kawaii dake ja Nai Shikimori-san" -f 1 -a -s 2>&1

echo "=== Starting Ririsa download (201 chapters) ==="
python3 -m memanga check -t "25-jigen no Ririsa" -f 1 -a -s 2>&1

echo "=== All downloads complete! ==="
