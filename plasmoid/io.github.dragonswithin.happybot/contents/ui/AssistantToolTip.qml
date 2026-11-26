/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.ToolTip {
    id: tip
    property color accent: Kirigami.Theme.highlightColor

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
        accent: tip.accent
        raised: true
    }
}
