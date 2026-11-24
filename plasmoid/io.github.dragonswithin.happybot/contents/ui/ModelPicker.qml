/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The popup's per-chat AI picker, a small drop-down shown in ResultsView.qml
 * beside the typing field (or in the header when the user types in the
 * panel's search bar). It is shown only when two or more AIs are set up.
 *
 * "Automatic" leaves the chat on the user's order of AIs (the AI Model
 * page); choosing one AI sends every request of this chat to that AI alone.
 * The choice lives in `session.chatModel` (AssistantSession.qml), which sends
 * it with each request and restores it when a saved chat is reopened; this
 * component only shows and changes it. Online AIs are marked "online" so the
 * user sees where their words would go.
 */
QQC2.ComboBox {
    id: picker

    required property var session

    readonly property var names: [""].concat(session.models.map(item => item.name))

    visible: session.models.length > 1
    enabled: !session.busy
    // A fixed width, so the popup (which resizes itself to its content) never
    // depends on the names. Plasma's own combo box made binding loops on its
    // implicit size here; the standard one, as on the settings pages, does not.
    Layout.preferredWidth: Kirigami.Units.gridUnit * 7.5
    model: [i18n("Automatic")].concat(session.models.map(item => item.online ? i18n("%1 (online)", item.name) : item.name))
    currentIndex: Math.max(0, names.indexOf(session.chatModel))
    onActivated: index => session.chatModel = names[index]

    Accessible.name: i18n("AI for this chat")
    QQC2.ToolTip.text: session.chatModel === ""
        ? i18n("Automatic: your AIs are asked in the order set on the AI Model page")
        : i18n("This chat uses %1 only", session.chatModel)
    QQC2.ToolTip.visible: hovered
}
