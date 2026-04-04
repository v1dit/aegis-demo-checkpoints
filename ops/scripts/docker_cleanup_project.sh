#!/usr/bin/env bash
set -euo pipefail

docker ps -a --filter "label=project=pantherhacks" -q | xargs -r docker rm -f
docker images --filter "label=project=pantherhacks" -q | xargs -r docker rmi -f
docker volume ls --filter "label=project=pantherhacks" -q | xargs -r docker volume rm
