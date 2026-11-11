#!/usr/bin/env bash
# Общие хелперы кэша архивов portable runtime (Python / Node.js).
# Кэш: virtual_env/cache/downloads; partial — рядом с целевым файлом.

ergoms_console_from_root() {
  local root="$1" key="$2" color="${3:-white}" stderr_flag="${4:-}"
  shift 4 || true
  local py="$root/virtual_env/python/bin/python"
  if [[ ! -x "$py" ]]; then
    py="$root/virtual_env/packages/python/bin/python3"
  fi
  local script="$root/core/deployment/scripts/ergoms_console.py"
  if [[ -x "$py" && -f "$script" ]]; then
    local args=("$script" --key "$key" --color "$color")
    [[ -n "$stderr_flag" ]] && args+=(--stderr)
    while [[ $# -gt 0 ]]; do
      args+=(--param "$1")
      shift
    done
    "$py" "${args[@]}"
    return 0
  fi
  echo "[$key]" >&2
  # До создания project venv отсутствие рендера не должно прерывать bootstrap с set -e.
  return 0
}

cached_runtime_archive_ok() {
  local path="$1"
  [[ -f "$path" && -s "$path" ]]
}

download_runtime_archive() {
  local url="$1"
  local dest="$2"
  local root="${3:-}"
  local partial="${dest}.partial"
  mkdir -p "$(dirname "$dest")"
  rm -f "$partial"

  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 15 --max-time 600 -o "$partial" "$url" || return 1
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$partial" "$url" || return 1
  else
    if [[ -n "$root" ]]; then
      ergoms_console_from_root "$root" runtime_archive_need_curl_wget red --stderr
    else
      echo "[ERROR] runtime_archive_need_curl_wget" >&2
    fi
    return 1
  fi

  if ! cached_runtime_archive_ok "$partial"; then
    if [[ -n "$root" ]]; then
      ergoms_console_from_root "$root" runtime_archive_empty red --stderr
    else
      echo "[ERROR] runtime_archive_empty" >&2
    fi
    rm -f "$partial"
    return 1
  fi
  mv -f "$partial" "$dest"
}

export -f ergoms_console_from_root cached_runtime_archive_ok download_runtime_archive
