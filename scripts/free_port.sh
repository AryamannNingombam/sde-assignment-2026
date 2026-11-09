# Sourced by eval.sh / crash_test.sh:  free_port <port>
# Clears whatever is listening on <port> so `docker compose up` can publish it:
#   1. Docker containers publishing the port are removed;
#   2. a stale host simulator (`python -m sim ...`) is stopped;
#   3. any OTHER host process is NOT killed: the script aborts and says who holds the port.
free_port() {
  local port=$1 ids pid cmd
  ids=$(docker ps -q --filter "publish=$port" 2>/dev/null || true)
  if [ -n "$ids" ]; then echo "free_port: removing container(s) publishing :$port"; docker rm -f $ids >/dev/null; sleep 1; fi
  for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
    cmd=$(ps -o command= -p "$pid" 2>/dev/null || true)
    case "$cmd" in
      *"-m sim"*) echo "free_port: stopping stale simulator pid $pid ($cmd)"; kill "$pid"; sleep 1 ;;
      *ocker*) ;;                                   # Docker Desktop's own port proxy
      *) echo "free_port: :$port is held by pid $pid ($cmd) - not ours, refusing to kill it" >&2; return 1 ;;
    esac
  done
}
