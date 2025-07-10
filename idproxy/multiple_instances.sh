#!/usr/bin/env bash
set -e

if [ ! -f "./data/idproxy_proxies_http" ]; then
  curl "$PROXIES_URL" | sed -E 's/^([^:]+):([^:]+):([^:]+):(.*)$/http:\/\/\3:\4@\1:\2/' | tr -d '\r' > ./data/idproxy_proxies_http
fi


if [[ -z "$INSTANCES" ]]; then
  echo "WARN: \$INSTANCES not set, only managing one" 1>&2
  INSTANCES=1
fi

if [[ -z "$@" ]]; then
  echo "ERROR: provide at least one docker compose argument" 1>&2
  exit 1
fi

BUILD_FLAG=""
if [[ "$*" == *--build* ]]; then
  BUILD_FLAG="--build"
  docker build -t idproxy-api api &
  docker build -t idproxy-ofutun lib/ofutun  &
  wait
fi

for INSTANCE_ID in $(seq 1 $INSTANCES);
do
  export INSTANCE_ID=$INSTANCE_ID
  export INSTANCE_PROXY=$(sed -n "${INSTANCE_ID}p" ./data/idproxy_proxies_http)
  if [[ -z "$INSTANCE_PROXY" ]]; then
    echo "ERROR: No proxy found for INSTANCE_ID=$INSTANCE_ID in ./data/idproxy_proxies_http" 1>&2
    exit 1
  fi
  echo "$INSTANCE_ID: using proxy $INSTANCE_PROXY"

  docker compose -p idproxy_instance_$INSTANCE_ID $@ &
done
wait
