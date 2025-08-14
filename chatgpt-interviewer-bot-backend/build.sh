#!/bin/bash
set -e  # Exit on any error

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

log "🚀 Starting build script..."

# ---------------------------
# 1. Setup Rust environment
# ---------------------------
log "Setting Rust environment variables..."
export CARGO_HOME=$HOME/.cargo
export RUSTUP_HOME=$HOME/.rustup
export PATH=$CARGO_HOME/bin:$PATH

# ---------------------------
# 2. Install Rust if missing
# ---------------------------
if ! command -v cargo >/dev/null; then
    log "Rust not found. Installing Rust toolchain..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
else
    log "✅ Rust already installed."
    if [ -f "$HOME/.cargo/env" ]; then
        log "Loading Rust environment..."
        source $HOME/.cargo/env
    fi
fi

# ---------------------------
# 3. Ensure stable Rust
# ---------------------------
log "Setting Rust to stable version..."
rustup default stable

# ---------------------------
# 4. Upgrade Python build tools
# ---------------------------
log "Upgrading pip, setuptools, wheel, and maturin..."
pip install --upgrade pip setuptools wheel maturin

# ---------------------------
# 5. Move to project directory
# ---------------------------
PROJECT_DIR="chatgpt-interviewer-bot-backend"
if [ -d "$PROJECT_DIR" ]; then
    log "Changing directory to $PROJECT_DIR..."
    cd "$PROJECT_DIR"
else
    log "❌ ERROR: Project folder '$PROJECT_DIR' not found!"
    exit 1
fi

# ---------------------------
# 6. Install Python dependencies
# ---------------------------
if [ -f requirements.txt ]; then
    log "Installing dependencies from requirements.txt..."
    pip install -r requirements.txt
else
    log "❌ ERROR: requirements.txt not found!"
    exit 1
fi

# ---------------------------
# 7. Verify critical package
# ---------------------------
log "Verifying pydantic-core installation..."
python -c "import pydantic_core; print('✅ pydantic-core version:', pydantic_core.__version__)" || {
    log "❌ ERROR: pydantic-core failed to import!"
    exit 1
}

log "🎉 Build script completed successfully!"
