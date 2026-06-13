#!/bin/bash
set -e

mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/tick-tick.service << 'EOF'
[Unit]
Description=tick-tick scheduler bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/kr8336/Desktop/Projects/tick-tick
ExecStart=/home/kr8336/Desktop/Projects/tick-tick/.venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/kr8336/Desktop/Projects/tick-tick/.env

[Install]
WantedBy=default.target
EOF

systemctl --user enable --now tick-tick
loginctl enable-linger "$USER"

echo "Done. Checking status..."
systemctl --user status tick-tick --no-pager
