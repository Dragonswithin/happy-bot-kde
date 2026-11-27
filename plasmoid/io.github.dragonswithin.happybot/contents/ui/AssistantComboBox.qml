/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Templates as T

import org.kde.kirigami as Kirigami

T.ComboBox {
    id: picker
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor

    implicitHeight: Math.max(Kirigami.Units.gridUnit * 1.75, contentItem.implicitHeight + 2 * padding)
    padding: Kirigami.Units.smallSpacing
    leftPadding: mirrored ? padding + indicator.width + padding : padding * 2
    rightPadding: mirrored ? padding * 2 : padding + indicator.width + padding
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    background: PopupControlBackground {
        nativeLook: picker.nativeLook
        accent: picker.accent
        highlighted: picker.hovered || picker.down
        emphasized: picker.visualFocus || picker.popup.visible
    }

    indicator: Kirigami.Icon {
        x: picker.mirrored ? picker.padding : picker.width - width - picker.padding
        y: (picker.height - height) / 2
        width: Kirigami.Units.iconSizes.small
        height: width
        source: "arrow-down"
    }

    contentItem: QQC2.Label {
        text: picker.displayText
        textFormat: Text.PlainText
        font: picker.font
        color: Kirigami.Theme.textColor
        opacity: picker.enabled ? 1 : 0.55
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    delegate: QQC2.ItemDelegate {
        id: option
        required property int index
        required property string modelData
        width: ListView.view.width
        text: modelData
        highlighted: picker.highlightedIndex === index
        background: AccentSelection { control: option; accent: picker.accent }
        contentItem: QQC2.Label {
            text: option.text
            textFormat: Text.PlainText
            color: Kirigami.Theme.textColor
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
    }

    popup: QQC2.Popup {
        y: picker.height + Kirigami.Units.smallSpacing
        width: picker.width
        padding: Kirigami.Units.smallSpacing
        implicitHeight: Math.min(options.contentHeight + topPadding + bottomPadding,
                                 Kirigami.Units.gridUnit * 12)
        background: PopupControlBackground {
            nativeLook: picker.nativeLook
            accent: picker.accent
            raised: true
        }
        contentItem: ListView {
            id: options
            clip: true
            model: picker.delegateModel
            currentIndex: picker.highlightedIndex
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}
        }
    }

    Accessible.name: i18n("AI for this chat")
    AssistantToolTip {
        nativeLook: picker.nativeLook
        accent: picker.accent
        text: session.chatModel === ""
            ? i18n("Automatic: your AIs are asked in the order set on the AI Model page")
            : i18n("This chat uses %1 only", session.chatModel)
        visible: picker.hovered && !picker.popup.visible
    }
}
