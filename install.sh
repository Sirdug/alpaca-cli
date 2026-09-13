#!/usr/bin/env bash
# Compatible with macOS's Bash 3.2 and Ubuntu Bash.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash install.sh [--mcp] [--python PATH] [--install-dir PATH] [--bin-dir PATH]

Install this checkout into a private virtual environment on macOS or Linux.
  --mcp              Include the optional MCP server (requires Python 3.12+).
  --python PATH      Python executable (default: python3; CLI requires 3.9+).
  --install-dir PATH Virtual environment (default: ~/.local/share/alpaca-cli).
  --bin-dir PATH     Command links (default: ~/.local/bin).
  --help            Show this help.

Run again with the same options after pulling updates to upgrade the installation.
No sudo is used and shell startup files are not modified.
EOF
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
python=python3
install_dir="$HOME/.local/share/alpaca-cli"
bin_dir="$HOME/.local/bin"
with_mcp=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --mcp) with_mcp=true; shift ;;
        --python|--install-dir|--bin-dir)
            [ "$#" -ge 2 ] && [ -n "$2" ] || die "$1 requires a value"
            case "$1" in
                --python) python=$2 ;;
                --install-dir) install_dir=$2 ;;
                --bin-dir) bin_dir=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
done

case "$(uname -s)" in
    Darwin) hint='Install Python with Homebrew: brew install python' ;;
    Linux) hint='On Ubuntu: sudo apt update && sudo apt install python3 python3-venv' ;;
    *) die 'This installer supports macOS and Linux. See README.md for Windows setup.' ;;
esac
command -v "$python" >/dev/null 2>&1 || die "Python not found: $python. $hint"
minimum=3.9
if "$with_mcp"; then minimum=3.12; fi
"$python" -c 'import sys; sys.exit(sys.version_info[:2] < tuple(map(int, sys.argv[1].split("."))))' "$minimum" \
    || die "Python $minimum or newer is required. Use --python to select it. $hint"

source_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[ -f "$source_dir/pyproject.toml" ] || die 'Run install.sh from a complete alpaca-cli checkout.'
# Resolve paths before creating anything; quoted arguments support spaces.
install_dir=$("$python" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$install_dir")
bin_dir=$("$python" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$bin_dir")
marker="$install_dir/.alpaca-cli-installer"
if [ -e "$install_dir" ] || [ -L "$install_dir" ]; then
    [ -f "$marker" ] && [ -f "$install_dir/pyvenv.cfg" ] \
        || die "Refusing to use an existing unmanaged directory: $install_dir"
fi
commands=(alpaca)
if "$with_mcp"; then commands+=(alpaca-mcp); fi
for name in "${commands[@]}"; do
    link="$bin_dir/$name"
    if [ -e "$link" ] || [ -L "$link" ]; then
        [ -L "$link" ] && [ "$(readlink "$link")" = "$install_dir/bin/$name" ] \
            || die "Refusing to replace an existing command: $link"
    fi
done

if [ ! -f "$marker" ]; then
    "$python" -m venv "$install_dir" \
        || die "Could not create the virtual environment. $hint. Retry with a new --install-dir."
    printf 'alpaca-cli\n' > "$marker"
fi
"$install_dir/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] < tuple(map(int, sys.argv[1].split("."))))' "$minimum" \
    || die "Existing environment needs Python $minimum+. Choose a new --install-dir and --bin-dir."
package="$source_dir"
if "$with_mcp"; then package="$source_dir[mcp]"; fi
"$install_dir/bin/python" -m pip install --upgrade "$package"
if "$with_mcp"; then
    "$install_dir/bin/python" -c 'from alpaca_cli import mcp_server'
fi
"$install_dir/bin/alpaca" --version
mkdir -p "$bin_dir"
for name in "${commands[@]}"; do
    ln -sfn "$install_dir/bin/$name" "$bin_dir/$name"
done
printf '\nInstalled commands in %s\n' "$bin_dir"
case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add this to your shell profile, or run it in this terminal:\n  export PATH=%q:"$PATH"\n' "$bin_dir" ;;
esac
printf 'Get started:\n  %q setup\n  %q doctor\n' "$bin_dir/alpaca" "$bin_dir/alpaca"
if "$with_mcp"; then printf 'MCP stdio command: %s/alpaca-mcp\n' "$bin_dir"; fi
