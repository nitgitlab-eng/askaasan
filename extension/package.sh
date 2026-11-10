#!/bin/sh
# Build the Chrome Web Store / Edge Add-ons zip with a production server baked in.
#   sh extension/package.sh https://aasan.example.com      ->  extension/dist/aasan-companion-<version>.zip
# The source folder keeps its development defaults (http://localhost:5173) so "Load unpacked" works unchanged.
# The store build instead gets: DEFAULT_SERVER = the given https origin, host_permissions = only that origin, and no
# localhost entries. https://*/* stays optional: task websites (and self-hosted Aasan servers) are asked for at runtime.
# Left out of the zip: tests, this script, the README and the icon generator.
set -eu
SERVER=${1:?usage: sh extension/package.sh https://your-aasan-address}
case "$SERVER" in https://*) ;; *) echo "The production address must start with https://" >&2; exit 1 ;; esac
SERVER=${SERVER%/}
HERE=$(cd "$(dirname "$0")" && pwd)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp "$HERE"/manifest.json "$HERE"/*.js "$HERE"/*.html "$HERE"/*.css "$HERE"/public_suffixes.json "$STAGE"/
mkdir "$STAGE/icons" && cp "$HERE"/icons/*.png "$STAGE/icons/"
SERVER="$SERVER" STAGE="$STAGE" node -e '
const fs = require("fs"), path = require("path");
const { SERVER, STAGE } = process.env;
const origin = new URL(SERVER).origin;
if (origin !== SERVER) throw new Error(`Use a bare origin like https://aasan.example.com, not ${SERVER}`);
const mf = path.join(STAGE, "manifest.json");
const m = JSON.parse(fs.readFileSync(mf, "utf8"));
m.host_permissions = [`${origin}/*`];
m.optional_host_permissions = (m.optional_host_permissions || []).filter((p) => !/localhost|127\.0\.0\.1/.test(p));
fs.writeFileSync(mf, JSON.stringify(m, null, 2) + "\n");
const lib = path.join(STAGE, "lib.js");
const src = fs.readFileSync(lib, "utf8");
const out = src.replace(/const DEFAULT_SERVER = "[^"]*";/, `const DEFAULT_SERVER = ${JSON.stringify(origin)};`);
if (out === src) throw new Error("DEFAULT_SERVER not found in lib.js");
fs.writeFileSync(lib, out);
'
VERSION=$(node -p 'require(process.argv[1]).version' "$STAGE/manifest.json")
mkdir -p "$HERE/dist"
ZIP="$HERE/dist/aasan-companion-$VERSION.zip"
rm -f "$ZIP"
(cd "$STAGE" && zip -qr "$ZIP" .)
echo "Built $ZIP for $SERVER"
