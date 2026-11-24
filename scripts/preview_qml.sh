#!/usr/bin/env bash
# Draws one of the widget's QML views to a PNG without Plasma, to look at a
# change without reinstalling the widget or restarting the panel.
#
#   scripts/preview_qml.sh COMPONENT OUT.png [PROPERTIES] [WIDTH] [HEIGHT]
#
# COMPONENT is a file name in the widget's contents/ui (for example
# WeatherCard.qml). PROPERTIES is QML property assignments for it, one per
# line or separated by ";", for example:
#   scripts/preview_qml.sh AnswerBody.qml /tmp/a.png 'text: "Run:\n```\nls\n```"'
# WIDTH and HEIGHT are the picture's size in pixels (default 520 by 400).
#
# How: the ui folder is copied to a temporary folder, KDE's translation calls
# (i18n, i18np) are pointed at a small stand-in that fills in %1, %2..., and
# the component is drawn offscreen (QT_QPA_PLATFORM=offscreen) with the KDE
# platform theme and Plasma's control style, over a dark background like the
# popup's, then saved with grabToImage. The checkout is not changed and the
# temporary folder is removed.
#
# Limits: views that need the running widget (Plasmoid, the daemon, the
# settings dialog's page object) cannot be drawn this way; give them plain
# values through PROPERTIES where they take them. Colours follow the desktop
# theme of the account running it. Needs qml6 (Qt 6 declarative tools).

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${REPO_ROOT}/plasmoid/io.github.dragonswithin.happybot/contents/ui"
component="${1:?usage: preview_qml.sh COMPONENT OUT.png [PROPERTIES] [WIDTH] [HEIGHT]}"
out="${2:?usage: preview_qml.sh COMPONENT OUT.png [PROPERTIES] [WIDTH] [HEIGHT]}"
properties="${3:-}"
width="${4:-520}"
height="${5:-400}"
[[ -f "${UI_DIR}/${component}" ]] || { printf 'preview_qml: no %s in contents/ui\n' "$component" >&2; exit 1; }
command -v qml6 >/dev/null || { printf 'preview_qml: qml6 is needed\n' >&2; exit 1; }
out="$(realpath -m -- "$out")"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
cp -r -- "$UI_DIR" "${work}/ui"
for file in "${work}"/ui/*.qml "${work}"/ui/*.js; do
  sed -i -E 's/\bi18np\(/Shim.i18np(/g; s/\bi18n\(/Shim.i18n(/g' "$file"
done
# JavaScript libraries cannot see QML singletons; give them the same stand-in directly.
for file in "${work}"/ui/*.js; do
  grep -q 'Shim\.' "$file" && printf '\nvar Shim = { i18n: function(f) { var t = String(f); for (var i = 1; i < arguments.length; i++) t = t.split("%%" + i).join(String(arguments[i])); return t; }, i18np: function(s, p, n) { return String(n === 1 ? s : p).split("%%1").join(String(n)); } };\n' >> "$file"
done
cat > "${work}/ui/Shim.qml" <<'EOF'
pragma Singleton
import QtQuick
QtObject {
    function i18n(format) {
        let text = String(format);
        for (let i = 1; i < arguments.length; i++) text = text.split("%" + i).join(String(arguments[i]));
        return text;
    }
    function i18np(singular, plural, count) {
        const extra = Array.prototype.slice.call(arguments, 3);
        return i18n.apply(null, [count === 1 ? singular : plural, count].concat(extra));
    }
}
EOF
printf 'singleton Shim 1.0 Shim.qml\n' >> "${work}/ui/qmldir"
cat > "${work}/ui/PreviewHarness.qml" <<EOF
import QtQuick
import QtQuick.Window
Window {
    id: preview
    width: ${width}; height: ${height}; visible: true
    Rectangle { anchors.fill: parent; color: "#202326" }
    ${component%.qml} {
        x: 12; y: 12; width: preview.width - 24
        ${properties//;/$'\n'        }
    }
    Timer {
        interval: 1500; running: true
        onTriggered: preview.contentItem.grabToImage(result => { result.saveToFile("${out}"); Qt.quit(); })
    }
}
EOF
(cd "${work}/ui" && QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=kde QT_QUICK_CONTROLS_STYLE=org.kde.desktop \
  timeout 20 qml6 PreviewHarness.qml 2>&1 | grep -v -E 'propertyCache|atspi' >&2 || true)
[[ -f "$out" ]] || { printf 'preview_qml: nothing was drawn (see the messages above)\n' >&2; exit 1; }
printf '%s\n' "$out"
