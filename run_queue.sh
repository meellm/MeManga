#!/bin/bash
cd ~/MeManga
source venv/bin/activate

# Wait for MakeHero to finish
echo "[$(date)] Waiting for MakeHero to complete..."
while pgrep -f "memanga.*Make Heroine" > /dev/null; do
    sleep 30
done

echo "[$(date)] Starting Shikimori download (201 chapters)..."
python3 -m memanga check -t "Kawaii dake ja Nai Shikimori-san" -f 1 -a -s -q 2>&1

echo "[$(date)] Starting Ririsa download (201 chapters)..."
python3 -m memanga check -t "25-jigen no Ririsa" -f 1 -a -s -q 2>&1

echo "[$(date)] All downloads complete!"
