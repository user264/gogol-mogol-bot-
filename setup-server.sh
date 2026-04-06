#!/bin/bash
# Run on a fresh Ubuntu/Debian server as root
set -e

# Install Docker
curl -fsSL https://get.docker.com | sh

# Clone repo
git clone https://github.com/user264/gogol-mogol-bot-.git ~/gogol-mogol-bot
cd ~/gogol-mogol-bot

# Create .env
cat > .env << 'EOF'
BOT_TOKEN=your-telegram-bot-token
DB_PASSWORD=change-me-strong-password
TZ=Asia/Almaty
EOF

echo "Edit .env with your real values, then run:"
echo "  cd ~/gogol-mogol-bot && docker compose up -d"
