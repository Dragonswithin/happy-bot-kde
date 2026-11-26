/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import org.kde.kirigami as Kirigami

Rectangle {
    required property var control
    required property color accent
    radius: Kirigami.Units.cornerRadius
    color: Qt.alpha(accent, control.highlighted || control.down ? 0.24 : control.hovered ? 0.12 : 0)
    border.color: control.visualFocus ? accent : "transparent"
}
