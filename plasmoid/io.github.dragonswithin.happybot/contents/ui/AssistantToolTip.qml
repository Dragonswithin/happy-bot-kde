/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.ToolTip {
    id: tip
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor

    Kirigami.Theme.colorSet: nativeLook ? Kirigami.Theme.Tooltip : Kirigami.Theme.Window
    delay: Kirigami.Units.toolTipDelay
    padding: Kirigami.Units.largeSpacing
    width: Math.min(implicitWidth, Kirigami.Units.gridUnit * 20)
    contentItem: QQC2.Label {
        text: tip.text
        textFormat: Text.PlainText
        font: tip.font
        color: Kirigami.Theme.textColor
        wrapMode: Text.Wrap
    }
    background: PopupControlBackground {
        nativeLook: tip.nativeLook
        accent: tip.accent
        raised: true
    }
}
