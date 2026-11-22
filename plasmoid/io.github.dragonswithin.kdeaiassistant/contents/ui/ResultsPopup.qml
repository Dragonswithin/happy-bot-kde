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
 * The one window that shows what the assistant is doing: the conversation
 * transcript from AssistantSession.qml, its status, and the context actions.
 * main.qml owns its visibility and anchors it to the applet.
 *
 * It runs in one of two modes, chosen by `inputInPopup`:
 *
 * - false (normal): the panel field keeps keyboard focus, so this window is
 *   a Tooltip-type surface that never takes focus. Buttons still work with
 *   the pointer. It closes when main.qml hides it.
 * - true (fallback and vertical panels): the window takes focus, shows its
 *   own input field, and closes itself when it is deactivated.
 *
 * `submitted` carries text typed into the embedded field; the panel field
 * reports its own text to main.qml directly. The window's size comes from
 * the applet's `popupWidth` and `popupHeight` settings.
 */
PlasmaCore.Dialog {
    id: popup

    required property AssistantSession session
    property bool inputInPopup: false
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26

    signal submitted(string text, string contextKind)
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

    mainItem: Item {
        implicitWidth: Kirigami.Units.gridUnit * popup.widthInGridUnits
        implicitHeight: Kirigami.Units.gridUnit * popup.heightInGridUnits

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true

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

            PlasmaComponents3.TextField {
                id: embeddedField
                Layout.fillWidth: true
                visible: popup.inputInPopup
                enabled: !popup.session.busy
                placeholderText: i18n("Ask or search anything…")
                Keys.onReturnPressed: popup.submitEmbedded("combined")
                Keys.onEnterPressed: popup.submitEmbedded("combined")
                Keys.onEscapePressed: popup.visible = false
            }

            PlasmaComponents3.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true

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

                PlasmaComponents3.Button {
                    text: i18n("Clipboard")
                    icon.name: "edit-paste"
                    enabled: !popup.session.busy
                    onClicked: popup.submitted(i18n("Use my clipboard as context and help me with it."), "clipboard")
                }

                PlasmaComponents3.Button {
                    text: i18n("Window")
                    icon.name: "window"
                    enabled: !popup.session.busy
                    onClicked: popup.submitted(i18n("Use my active window as context and help me with it."), "window")
                }

                PlasmaComponents3.Button {
                    text: i18n("Screenshot")
                    icon.name: "spectacle"
                    onClicked: popup.session.screenshotContext()
                }
            }
        }
    }

    function submitEmbedded(contextKind) {
        const text = embeddedField.text.trim();
        if (text.length > 0) {
            embeddedField.text = "";
            popup.submitted(text, contextKind);
        }
    }
}
