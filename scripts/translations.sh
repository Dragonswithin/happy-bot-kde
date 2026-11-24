#!/usr/bin/env bash
# Translations for the Happy Bot panel applet: the template translators start
# from, keeping each language up to date with it, and compiling them into an
# applet package so Plasma shows them.
#
# Translations live in po/<language>.po (for example po/de.po), one file per
# language, in the gettext domain plasma_applet_io.github.dragonswithin.happybot,
# which Plasma loads for this applet. They come from translators; nothing here
# writes a translation. The daemon's own messages (src/happy_bot) are English
# only for now.
#
#   scripts/translations.sh template      write po/<domain>.pot from every i18n/i18np
#                                         call in the applet's QML and JavaScript
#                                         (generated, not kept in git)
#   scripts/translations.sh merge         refresh the template, then bring every
#                                         po/*.po up to date with it (msgmerge)
#   scripts/translations.sh build DIR     compile every po/*.po into the applet
#                                         package at DIR, as
#                                         DIR/contents/locale/<lang>/LC_MESSAGES/<domain>.mo
#   scripts/translations.sh languages     print the languages that have a po file
#
# scripts/install.sh and packaging/arch/PKGBUILD run "build" on a copy of the
# package they install, so compiled files never land in the checkout. With no
# po files, "build" does nothing and succeeds.
#
# Needs gettext (xgettext, msgmerge, msgfmt) for template, merge and build.
# Exit status is non-zero on any failure; a broken po file stops "build".

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APPLET_ID="io.github.dragonswithin.happybot"
DOMAIN="plasma_applet_${APPLET_ID}"
APPLET_DIR="${REPO_ROOT}/plasmoid/${APPLET_ID}"
PO_DIR="${REPO_ROOT}/po"

need() {
  command -v "$1" >/dev/null 2>&1 || { printf 'translations: %s is needed (install gettext)\n' "$1" >&2; exit 1; }
}

po_files() {
  shopt -s nullglob
  local files=("${PO_DIR}"/*.po)
  shopt -u nullglob
  printf '%s\n' "${files[@]}"
}

template() {
  need xgettext
  mkdir -p "$PO_DIR"
  (cd "$APPLET_DIR" && find . \( -name '*.qml' -o -name '*.js' \) -print0 | sort -z \
    | xargs -0 xgettext --from-code=UTF-8 -C -ki18n -ki18np:1,2 --package-name="Happy Bot" \
        -o "${PO_DIR}/${DOMAIN}.pot")
  printf 'wrote %s (%s strings)\n' "po/${DOMAIN}.pot" "$(($(grep -c '^msgid "' "${PO_DIR}/${DOMAIN}.pot") - 1))"
}

merge() {
  need msgmerge
  template
  local file
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    msgmerge --quiet --update --backup=none "$file" "${PO_DIR}/${DOMAIN}.pot"
    printf 'updated po/%s\n' "$(basename -- "$file")"
  done < <(po_files)
}

build() {
  local target="${1:?usage: translations.sh build PACKAGE_DIR}"
  [[ -d "${target}/contents" ]] || { printf 'translations: %s is not an applet package\n' "$target" >&2; exit 1; }
  local file lang count=0
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    need msgfmt
    lang="$(basename -- "$file" .po)"
    install -d "${target}/contents/locale/${lang}/LC_MESSAGES"
    msgfmt --check -o "${target}/contents/locale/${lang}/LC_MESSAGES/${DOMAIN}.mo" "$file"
    count=$((count + 1))
  done < <(po_files)
  printf 'compiled %d translation(s)\n' "$count"
}

case "${1:-}" in
  template) template ;;
  merge) merge ;;
  build) build "${2:-}" ;;
  languages) po_files | xargs -r -n1 basename | sed 's/\.po$//' ;;
  *) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
