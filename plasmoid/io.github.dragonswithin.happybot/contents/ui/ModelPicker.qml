/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

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
AssistantComboBox {
    id: picker
    objectName: "chatModelPicker"
    required property var session
    readonly property var names: [""].concat(session.models.map(item => item.name))

    visible: session.models.length > 1
    enabled: !session.busy
    Layout.preferredWidth: Kirigami.Units.gridUnit * 7.5
    model: [i18n("Automatic")].concat(session.models.map(item => item.online ? i18n("%1 (online)", item.name) : item.name))
    currentIndex: Math.max(0, names.indexOf(session.chatModel))
    onActivated: index => session.chatModel = names[index]
}
