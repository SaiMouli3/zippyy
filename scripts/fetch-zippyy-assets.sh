#!/usr/bin/env bash
# Downloads the zippyy.ai homepage assets listed in docs/zippyy-design-system.md
# into frontend/public/brand/ (git-ignored). Only run this if you own or are
# licensed to use these files.
set -euo pipefail

BASE="https://zippyy.ai/wp-content/uploads"
OUT="$(cd "$(dirname "$0")/.." && pwd)/frontend/public/brand"
mkdir -p "$OUT"

ASSETS=(
  2025/11/logo-1.svg 2025/11/logo.svg
  2025/12/cropped-Favicon-24px-size-192x192.jpg
  2025/11/4f835bcd-e4a3-4541-b37e-fbb3a616f6c7-2.jpeg 2025/11/Group-1321314881.svg
  2025/11/menufirst-1.svg 2025/12/Delivery-notification-icon-1.svg 2025/12/Vector.svg
  2026/02/hand_package_24dp_FFFFFF_FILL1_wght400_GRAD0_opsz24-1-1.svg
  2026/02/handshake_24dp_FFFFFF_FILL1_wght400_GRAD0_opsz24-1.svg
  2025/11/image-6-1.png 2025/11/image-96-1.png 2025/11/image-97-1.png 2025/11/image-102.png
  2025/11/image-103.png 2025/11/image-104.png 2025/11/image-106-1.png 2025/11/image-107-1.png
  2025/11/tiremarketlogo-1-1.png 2025/11/kayura_effect_llp_logo_1-removebg-preview-1-1.png
  2025/11/Group-1321314902-1-scaled.png 2025/11/Frame-1618873407-scaled.png 2025/11/Frame-1618873408.png
  2025/11/Customer-2.png 2025/11/IMG-20251127-WA0012.jpg 2025/11/IMG-20251127-WA0011.jpg
  2025/12/Group-1321314964.png 2025/12/Frame-32.png 2025/11/Frame-1618873295-2.png
  2025/11/Frame-1511128813-9.png 2025/11/Frame-1511128814-10.png
  2025/11/Frame-1511128815-10.png 2025/11/Frame-1511128816-7.png
  2025/11/Ornament-57.png 2025/11/footer-line.svg 2025/11/footer-line-1.svg
  2025/11/cta.svg 2025/11/footer-side-circle.svg
)
for i in 1 2 3 4 5 6 8 9 10 11 12; do ASSETS+=("2025/11/header-menu-icon${i}-1.svg"); done
for i in 1 2 3; do ASSETS+=("2025/11/resorce-icon${i}-1.svg"); done
for i in 1 2 3 4 5; do ASSETS+=("2025/11/about-icon${i}-1.svg"); done

for path in "${ASSETS[@]}"; do
  name="$(basename "$path")"
  if curl -fsSL -A "Mozilla/5.0" -o "$OUT/$name" "$BASE/$path"; then
    echo "ok   $name"
  else
    echo "FAIL $name" >&2
  fi
done
