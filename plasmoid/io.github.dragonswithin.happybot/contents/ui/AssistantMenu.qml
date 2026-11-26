/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Menu {
    id: menu
    property color accent: Kirigami.Theme.highlightColor

    background: PopupControlBackground {
        implicitWidth: Kirigami.Units.gridUnit * 8
        accent: menu.accent
        raised: true
    }
}
