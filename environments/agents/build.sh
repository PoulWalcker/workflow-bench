#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: environments/agents/build.sh <sapiens-source> [compose-build-options]" >&2
    exit 2
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
source_dir=$(cd "$1" && pwd -P)
shift

source_root=$(git -C "$source_dir" rev-parse --show-toplevel)
if [[ "$source_dir" != "$source_root" ]]; then
    echo "Sapiens source must be the repository root" >&2
    exit 2
fi

SAPIENS_REVISION=$(<"$script_dir/SAPIENS_REVISION")
source_revision=$(git -C "$source_dir" rev-parse HEAD)
if [[ "$source_revision" != "$SAPIENS_REVISION" ]]; then
    echo "Sapiens source revision $source_revision differs from pinned $SAPIENS_REVISION" >&2
    exit 2
fi

SAPIENS_ARCHIVE_CONTEXT=$(mktemp -d)
trap 'rm -rf "$SAPIENS_ARCHIVE_CONTEXT"' EXIT
git -C "$source_dir" archive --format=tar "$SAPIENS_REVISION" \
    sapiens prompts web license sapiens4 \
    | tar -xf - -C "$SAPIENS_ARCHIVE_CONTEXT"
printf '%s\n' "$SAPIENS_REVISION" > "$SAPIENS_ARCHIVE_CONTEXT/REVISION"

export SAPIENS_ARCHIVE_CONTEXT SAPIENS_REVISION
docker compose -f "$script_dir/compose.yaml" build --pull "$@"
