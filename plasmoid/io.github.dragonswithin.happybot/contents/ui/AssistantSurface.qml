/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import org.kde.kirigami as Kirigami

Rectangle {
    id: surface
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor
    readonly property int inset: Kirigami.Units.largeSpacing * 1.5

    radius: Kirigami.Units.cornerRadius * 3
    color: Kirigami.Theme.backgroundColor
    border.color: nativeLook ? Qt.alpha(Kirigami.Theme.textColor, 0.22) : Qt.alpha(accent, 0.23)
    gradient: nativeLook ? null : mascotGradient
    Gradient {
        id: mascotGradient
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(surface.accent, 0.06)) }
        GradientStop { position: 1; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(surface.accent, 0.18)) }
    }
    clip: true
}
