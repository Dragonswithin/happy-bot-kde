/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ShadowedRectangle {
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor
    property bool highlighted: false
    property bool emphasized: false
    property bool raised: false

    radius: Kirigami.Units.cornerRadius * 2
    color: nativeLook && !highlighted ? Kirigami.Theme.backgroundColor
        : Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(accent, highlighted ? 0.24 : 0.13))
    border.width: 1
    border.color: emphasized ? accent : Qt.alpha(nativeLook ? Kirigami.Theme.textColor : accent, 0.38)
    shadow.yOffset: 2
    shadow.color: Qt.rgba(0, 0, 0, 0.27)
    shadow.size: raised ? 8 : 0
}
