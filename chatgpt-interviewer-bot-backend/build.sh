#!/bin/bash
set -e  # exit immediately if a command fails

# Setup Cargo and Rustup environment directories
export CARGO_HOME=$HOME/.cargo
export RUSTUP_HOME=$HOME/.rustup
export PATH=$CARGO_HOME/bin:$PATH

# Install Rust toolchain if missing
if ! command -v cargo >/dev/null; then
  echo "Installing Rust toolchain..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi

# Source Rust environment for this shell session
source $HOME/.cargo/env

# Set default Rust toolchain to stable
rustup default stable

# Go to your backend directory and install Python requirements
cd chatgpt-interviewer-bot-backend
pip install -r requirements.txt
