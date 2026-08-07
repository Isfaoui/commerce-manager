#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f "caisse.db" ]; then
    echo "Premiere installation - preparation de la base de donnees..."
    pip3 install -r requirements.txt --quiet
    python3 database/seed.py
fi

python3 main.py
