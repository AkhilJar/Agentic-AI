#!/bin/bash
set -e  # Exit immediately on error

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

log "🚀 Starting deployment process..."

# ---------------------------
# Step 1: Upgrade Python build tools
# ---------------------------
log "📦 Upgrading pip, setuptools, and wheel..."
python3 -m pip install --upgrade pip setuptools wheel

# ---------------------------
# Step 2: Check if Rust is needed
# ---------------------------
if grep -q "pydantic" requirements.txt || grep -q "maturin" requirements.txt; then
    log "🦀 Rust might be required for some dependencies. Checking..."
    export CARGO_HOME=$HOME/.cargo
    export RUSTUP_HOME=$HOME/.rustup
    export PATH=$CARGO_HOME/bin:$PATH

    if ! command -v cargo >/dev/null; then
        log "📥 Installing Rust toolchain..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source $HOME/.cargo/env
    else
        log "✅ Rust already installed."
        if [ -f "$HOME/.cargo/env" ]; then
            log "🔄 Loading Rust environment..."
            source $HOME/.cargo/env
        fi
    fi

    log "📌 Setting Rust to stable version..."
    rustup default stable
else
    log "✅ No Rust-heavy packages detected. Skipping Rust installation."
fi

# ---------------------------
# Step 3: Change to project directory
# ---------------------------
if [ -d "chatgpt-interviewer-bot-backend" ]; then
    log "📂 Changing directory to project folder..."
    cd chatgpt-interviewer-bot-backend
else
    log "❌ ERROR: Project folder 'chatgpt-interviewer-bot-backend' not found!"
    exit 1
fi

# ---------------------------
# Step 4: Install Python dependencies
# ---------------------------
if [ -f requirements.txt ]; then
    log "📜 Installing dependencies from requirements.txt..."
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
else
    log "❌ ERROR: requirements.txt not found in project folder!"
    exit 1
fi

# ---------------------------
# Step 5: Verify key packages
# ---------------------------
log "🔍 Verifying installed packages..."
python3 - <<'EOF'
try:
    import pydantic_core
    print(f"✅ pydantic-core version: {pydantic_core.__version__}")
except ImportError:
    print("⚠️ WARNING: pydantic-core not installed (may not be needed).")
EOF

log "🎉 Deployment completed successfully."
