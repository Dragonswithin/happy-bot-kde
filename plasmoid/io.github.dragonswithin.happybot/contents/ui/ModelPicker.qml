/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtQuick.Templates as T

import org.kde.kirigami as Kirigami

/**
 * The popup's per-chat AI picker, a small drop-down shown in ResultsView.qml
 * beside the typing field in both assistant windows. It is shown only when two or more AIs are set up.
 *
 * "Automatic" leaves the chat on the user's order of AIs (the AI Model
 * page); choosing one AI sends every request of this chat to that AI alone.
 * The choice lives in `session.chatModel` (AssistantSession.qml), which sends
 * it with each request and restores it when a saved chat is reopened; this
 * component only shows and changes it. Online AIs are marked "online" so the
 * user sees where their words would go.
 */
T.ComboBox {
    id: picker
    objectName: "chatModelPicker"

    required property var session
    property color accent: Kirigami.Theme.highlightColor

    readonly property var names: [""].concat(session.models.map(item => item.name))

    visible: session.models.length > 1
    enabled: !session.busy
    // Keep the composer width independent of the length of a model name.
    Layout.preferredWidth: Kirigami.Units.gridUnit * 7.5
    implicitHeight: Math.max(Kirigami.Units.gridUnit * 1.75, contentItem.implicitHeight + 2 * padding)
    padding: Kirigami.Units.smallSpacing
    leftPadding: mirrored ? padding + indicator.width + padding : padding * 2
    rightPadding: mirrored ? padding * 2 : padding + indicator.width + padding
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    model: [i18n("Automatic")].concat(session.models.map(item => item.online ? i18n("%1 (online)", item.name) : item.name))
    currentIndex: Math.max(0, names.indexOf(session.chatModel))
    onActivated: index => session.chatModel = names[index]

    background: PopupControlBackground {
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
        accent: picker.accent
        text: session.chatModel === ""
            ? i18n("Automatic: your AIs are asked in the order set on the AI Model page")
            : i18n("This chat uses %1 only", session.chatModel)
        visible: picker.hovered && !picker.popup.visible
    }
}
