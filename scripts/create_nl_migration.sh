#!/usr/bin/env bash
set -Eeuo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 \"<description>\"" >&2
    exit 1
fi

description=$1

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! [[ -x "$(command -v uv)" ]]; then
    echo "ERR: uv not found. Install with pip install uv" >&2
    exit 1
fi

max=0

for f in $script_dir/../migrations_nl/versions/[0-9][0-9][0-9][0-9]_*.py; do
    [ -e "$f" ] || continue

    n=$(basename "$f")
    n=${n%%_*}

    [ "$n" -gt "$max" ] && max=$n
done

next=$(printf "%04d\n" $((10#$max + 1)))

echo "$next $description"

uv run flask db revision -d migrations_nl --rev-id $next -m "$description"

exit 0
