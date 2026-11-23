/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras

/**
 * The one window that shows what the assistant found and is doing. From top
 * to bottom: instant file-search hits from AssistantSession.qml, a search
 * error line when the last search failed, and the conversation when
 * `showConversation` is set: a status line with Stop and New, the entries
 * (the user's requests, the assistant's Markdown answers as they stream in,
 * one line per tool call with its state, notices and errors), and two quick
 * requests. main.qml owns
 * its visibility, which hit is selected, and anchors it to the applet.
 *
 * It runs in one of two modes, chosen by `inputInPopup`:
 *
 * - false (normal): the panel field keeps keyboard focus, so this window is
 *   a Tooltip-type surface that never takes focus. Rows and buttons still
 *   work with the pointer. It closes when main.qml hides it.
 * - true (button mode and vertical panels): the window takes focus, shows
 *   its own input field, and closes itself when it is deactivated.
 *
 * The embedded field reports exactly what PanelBar.qml reports
 * (`queryEdited`, `accepted`, `selectionMove`) so main.qml treats both the
 * same. `hitActivated(location)` is a clicked result or a link clicked in
 * an answer; `quickRequest(text)` is a canned request from the Clipboard
 * and Window buttons; `closeRequested` is the close button.
 *
 * Height follows content: with only hits showing the window is as tall as
 * the rows need; with the conversation showing it uses the configured
 * `heightInGridUnits`.
 */
PlasmaCore.Dialog {
    id: popup

    required property AssistantSession session
    property bool inputInPopup: false
    property bool showConversation: false
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26

    readonly property bool hasHits: session.hits.length > 0
    readonly property bool hasSearchError: session.searchError.length > 0

    signal queryEdited(string text)
    signal accepted(string text)
    signal selectionMove(int delta)
    signal hitActivated(string location)
    signal quickRequest(string text)
    signal closeRequested()
    signal dismissed()

    type: inputInPopup ? PlasmaCore.Dialog.AppletPopup : PlasmaCore.Dialog.Tooltip
    flags: inputInPopup ? Qt.Dialog : (Qt.ToolTip | Qt.WindowDoesNotAcceptFocus)
    hideOnWindowDeactivate: inputInPopup
    backgroundHints: PlasmaCore.Dialog.StandardBackground

    onVisibleChanged: {
        if (visible && inputInPopup) {
            requestActivate();
            embeddedField.forceActiveFocus();
        } else if (!visible) {
            popup.dismissed();
        }
    }

    function clearInput() {
        embeddedField.text = "";
    }

    mainItem: Item {
        id: content

        readonly property int conversationHeight: Kirigami.Units.gridUnit * popup.heightInGridUnits
        readonly property bool conversationVisible: popup.showConversation || (popup.inputInPopup && !popup.hasHits)

        implicitWidth: Kirigami.Units.gridUnit * popup.widthInGridUnits
        implicitHeight: conversationVisible
            ? conversationHeight
            : Math.min(conversationHeight, column.implicitHeight)

        ColumnLayout {
            id: column
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.TextField {
                id: embeddedField
                Layout.fillWidth: true
                visible: popup.inputInPopup
                placeholderText: i18n("Ask or search anything…")
                onTextChanged: popup.queryEdited(text)
                Keys.onReturnPressed: popup.accepted(text.trim())
                Keys.onEnterPressed: popup.accepted(text.trim())
                Keys.onDownPressed: popup.selectionMove(1)
                Keys.onUpPressed: popup.selectionMove(-1)
                Keys.onEscapePressed: {
                    if (text.length > 0) {
                        text = "";
                    } else {
                        popup.visible = false;
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: popup.hasHits
                spacing: 0

                Repeater {
                    model: popup.session.hits

                    PlasmaComponents3.ItemDelegate {
                        id: row

                        required property int index
                        required property var modelData

                        Layout.fillWidth: true
                        highlighted: index === popup.selectedIndex
                        onClicked: popup.hitActivated(modelData.location)

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing

                            Kirigami.Icon {
                                source: row.modelData.kind === "folder" ? "folder"
                                    : row.modelData.kind === "link" ? "internet-web-browser"
                                    : "text-x-generic"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: row.modelData.title
                                    elide: Text.ElideRight
                                    textFormat: Text.PlainText
                                }

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: row.modelData.location
                                    elide: Text.ElideMiddle
                                    textFormat: Text.PlainText
                                    font: Kirigami.Theme.smallFont
                                    opacity: 0.7
                                }
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: popup.hasSearchError

                Kirigami.Icon {
                    source: "dialog-warning"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: popup.session.searchError
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                visible: content.conversationVisible && (popup.hasHits || popup.hasSearchError)
            }

            RowLayout {
                Layout.fillWidth: true
                visible: content.conversationVisible

                PlasmaExtras.Heading {
                    Layout.fillWidth: true
                    level: 4
                    text: popup.session.statusText
                    elide: Text.ElideRight
                }

                QQC2.BusyIndicator {
                    running: popup.session.busy
                    visible: running
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "process-stop"
                    text: i18n("Stop")
                    visible: popup.session.busy
                    onClicked: popup.session.cancel()
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "document-new"
                    text: i18n("New")
                    display: QQC2.AbstractButton.IconOnly
                    PlasmaComponents3.ToolTip.text: i18n("Start a new conversation")
                    PlasmaComponents3.ToolTip.visible: hovered
                    onClicked: popup.session.newChat()
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "window-close"
                    text: i18n("Close")
                    display: QQC2.AbstractButton.IconOnly
                    PlasmaComponents3.ToolTip.text: i18n("Close (Esc)")
                    PlasmaComponents3.ToolTip.visible: hovered
                    onClicked: popup.closeRequested()
                }
            }

            PlasmaComponents3.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: content.conversationVisible

                ListView {
                    id: transcript

                    model: popup.session.entries
                    spacing: Kirigami.Units.smallSpacing
                    clip: true

                    function followEnd() {
                        Qt.callLater(transcript.positionViewAtEnd);
                    }
                    onCountChanged: followEnd()
                    onContentHeightChanged: {
                        if (popup.session.busy) {
                            followEnd();
                        }
                    }

                    PlasmaExtras.PlaceholderMessage {
                        anchors.centerIn: parent
                        width: parent.width - Kirigami.Units.gridUnit * 2
                        visible: transcript.count === 0
                        text: i18n("Type a request and press Enter.")
                    }

                    delegate: Item {
                        id: entry

                        required property string kind
                        required property string text
                        required property string state

                        width: transcript.width
                        implicitHeight: body.implicitHeight

                        ColumnLayout {
                            id: body
                            width: parent.width
                            spacing: 0

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                visible: entry.kind === "user"
                                text: entry.text
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                font.bold: true
                                topPadding: Kirigami.Units.smallSpacing
                            }

                            TextEdit {
                                Layout.fillWidth: true
                                visible: entry.kind === "assistant"
                                text: entry.text
                                textFormat: TextEdit.MarkdownText
                                wrapMode: TextEdit.Wrap
                                readOnly: true
                                selectByMouse: true
                                activeFocusOnPress: popup.inputInPopup
                                color: Kirigami.Theme.textColor
                                selectionColor: Kirigami.Theme.highlightColor
                                selectedTextColor: Kirigami.Theme.highlightedTextColor
                                font: Kirigami.Theme.defaultFont
                                onLinkActivated: link => popup.hitActivated(link)

                                HoverHandler {
                                    cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                visible: entry.kind === "tool"
                                spacing: Kirigami.Units.smallSpacing

                                Kirigami.Icon {
                                    source: entry.state === "failed" ? "dialog-warning"
                                        : entry.state === "ok" ? "dialog-ok" : "system-run"
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                    opacity: 0.7
                                }

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: entry.state === "failed" ? i18n("%1 (failed)", entry.text) : entry.text
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    font: Kirigami.Theme.smallFont
                                    opacity: 0.7
                                }
                            }

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                visible: entry.kind === "error" || entry.kind === "notice"
                                text: entry.text
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                font: entry.kind === "notice" ? Kirigami.Theme.smallFont : Kirigami.Theme.defaultFont
                                color: entry.kind === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.disabledTextColor
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: content.conversationVisible

                PlasmaComponents3.Button {
                    text: i18n("Clipboard")
                    icon.name: "edit-paste"
                    enabled: !popup.session.busy
                    onClicked: popup.quickRequest(i18n("Look at what is on my clipboard and help me with it."))
                }

                PlasmaComponents3.Button {
                    text: i18n("Window")
                    icon.name: "window"
                    enabled: !popup.session.busy
                    onClicked: popup.quickRequest(i18n("Look at my active window and tell me what you can help with."))
                }
            }
        }
    }
}
