#!/usr/bin/env bash
# Policy example: measure an explicit node, then select it only when reachable.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  printf 'Usage: bash %s GROUP NODE TEST_URL\n' "$0" >&2
  exit 2
fi

clashier --output json proxy probe --group "$1" --name "$2" --url "$3" |
  jq -ce '
    if .ok and .data.status == "reachable" then
      {group: .data.group, name: .data.name,
       context: (.context | {instance_id, profile_uid})}
    else error("candidate is not reachable") end' |
  clashier --output json proxy select --input-json -
