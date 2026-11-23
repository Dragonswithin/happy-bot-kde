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
 * error line when the last search failed, and the conversation (status,
 * transcript, context actions) when `showConversation` is set. main.qml owns
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
 * same. `hitActivated(location)` is a clicked result; `contextRequested`
 * carries a canned request from the Clipboard and Window buttons.
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
    signal contextRequested(string text, string contextKind)
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
                    icon.name: "document-new"
                    text: i18n("New")
                    display: QQC2.AbstractButton.IconOnly
                    PlasmaComponents3.ToolTip.text: i18n("Start a new conversation")
                    PlasmaComponents3.ToolTip.visible: hovered
                    onClicked: popup.session.newChat()
                }
            }

            PlasmaComponents3.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: content.conversationVisible

                QQC2.TextArea {
                    text: popup.session.hasTranscript
                        ? popup.session.transcript
                        : i18n("Type a request and press Enter.")
                    readOnly: true
                    wrapMode: Text.Wrap
                    selectByMouse: true
                    activeFocusOnPress: popup.inputInPopup
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: content.conversationVisible

                PlasmaComponents3.Button {
                    text: i18n("Clipboard")
                    icon.name: "edit-paste"
                    enabled: !popup.session.busy
                    onClicked: popup.contextRequested(i18n("Use my clipboard as context and help me with it."), "clipboard")
                }

                PlasmaComponents3.Button {
                    text: i18n("Window")
                    icon.name: "window"
                    enabled: !popup.session.busy
                    onClicked: popup.contextRequested(i18n("Use my active window as context and help me with it."), "window")
                }

                PlasmaComponents3.Button {
                    text: i18n("Screenshot")
                    icon.name: "spectacle"
                    onClicked: popup.session.screenshotContext()
                }
            }
        }
    }
}
