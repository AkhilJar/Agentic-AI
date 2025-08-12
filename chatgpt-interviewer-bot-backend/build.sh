#!/bin/bash
set -e

export CARGO_HOME=$HOME/.cargo
export RUSTUP_HOME=$HOME/.rustup
export PATH=$CARGO_HOME/bin:$PATH

if ! command -v cargo >/dev/null; then
  echo "Installing Rust toolchain..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

  # Source rust environment after installation
  source $HOME/.cargo/env
else
  # If Rust is already installed, source env anyway (if file exists)
  if [ -f "$HOME/.cargo/env" ]; then
    source $HOME/.cargo/env
  fi
fi

# Set default Rust version (stable)
rustup default stable

# Now install Python dependencies
cd chatgpt-interviewer-bot-backend
pip install -r requirements.txt
