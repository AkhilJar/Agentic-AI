#!/bin/bash
export CARGO_HOME=$HOME/.cargo
export RUSTUP_HOME=$HOME/.rustup
export PATH=$CARGO_HOME/bin:$PATH

if ! command -v cargo >/dev/null; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi

source $HOME/.cargo/env
rustup default stable

cd chatgpt-interviewer-bot-backend
pip install -r requirements.txt
