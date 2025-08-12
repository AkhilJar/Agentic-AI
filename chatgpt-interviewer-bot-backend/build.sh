#!/bin/bash
set -e  # exit if any command fails

# Setup Rust environment variables
export CARGO_HOME=$HOME/.cargo
export RUSTUP_HOME=$HOME/.rustup
export PATH=$CARGO_HOME/bin:$PATH

# Install Rust if missing
if ! command -v cargo >/dev/null; then
  echo "Installing Rust toolchain..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source $HOME/.cargo/env
else
  if [ -f "$HOME/.cargo/env" ]; then
    source $HOME/.cargo/env
  fi
fi

# Set stable Rust as default
rustup default stable

# Upgrade pip tools to get latest wheels support
pip install --upgrade pip setuptools wheel

# Move to your project folder and install dependencies
cd chatgpt-interviewer-bot-backend
pip install -r requirements.txt
