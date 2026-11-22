/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtCore as QtCore
import QtQuick

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

/**
 * Root of the panel applet. It composes the three visual parts around one
 * AssistantSession and owns the rules that connect them:
 *
 * - Which form the panel shows. A horizontal panel gets the inline text
 *   field (PanelBar.qml). A vertical panel, or the `inputInPopup` setting,
 *   gets the icon (CompactRepresentation.qml) and typing happens inside
 *   ResultsPopup.qml instead.
 * - Keyboard focus. A panel only accepts key input while an applet reports
 *   AcceptingInputStatus, so `wantsInput` drives `Plasmoid.status` and is
 *   set before the field is focused and cleared when the field loses focus.
 * - Popup visibility. The popup opens on submit, reopens when the field
 *   regains focus with a conversation in progress, and closes when focus
 *   leaves the field.
 *
 * The applet's activation shortcut (set by the user in the applet's
 * Keyboard Shortcuts page) focuses the field or opens the popup.
 *
 * The daemon address defaults to the per-uid loopback port used by
 * src/kde_ai_assistant_daemon.py and can be overridden with the `daemonUrl`
 * setting in contents/config/main.xml.
 */
PlasmoidItem {
    id: root

    readonly property string runtimeLocation: String(QtCore.StandardPaths.writableLocation(QtCore.StandardPaths.RuntimeLocation))
    readonly property int sessionUid: {
        const match = runtimeLocation.match(/\/run\/user\/([0-9]+)/);
        return match ? parseInt(match[1]) : 1000;
    }
    readonly property int defaultDaemonPort: 19000 + Math.max(0, sessionUid - 1000)
    readonly property string configuredDaemonUrl: Plasmoid.configuration.daemonUrl || ""
    readonly property string daemonUrl: configuredDaemonUrl.length > 0
        ? configuredDaemonUrl
        : "http://127.0.0.1:" + defaultDaemonPort

    readonly property bool inputInPopup: Plasmoid.configuration.inputInPopup
        || Plasmoid.formFactor === PlasmaCore.Types.Vertical
    property bool wantsInput: false

    Plasmoid.icon: "search"
    Plasmoid.title: i18n("AI Assistant")
    Plasmoid.status: {
        if (wantsInput) {
            return PlasmaCore.Types.AcceptingInputStatus;
        }
        return session.busy ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus;
    }
    toolTipSubText: session.statusText
    activationTogglesExpanded: false
    preferredRepresentation: inputInPopup ? compactRepresentation : fullRepresentation

    AssistantSession {
        id: session
        daemonUrl: root.daemonUrl
    }

    ResultsPopup {
        id: popup
        session: session
        inputInPopup: root.inputInPopup
        visualParent: root
        location: Plasmoid.location
        onSubmitted: (text, contextKind) => session.ask(text, contextKind)
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        onClicked: popup.visible = !popup.visible
    }

    fullRepresentation: PanelBar {
        id: bar
        busy: session.busy
        statusText: session.statusText
        offline: session.status === "offline"

        onFocusRequested: root.focusBar()
        onSubmitted: text => {
            if (session.ask(text, "combined")) {
                bar.clear();
                popup.visible = true;
            }
        }
        onDismissed: {
            popup.visible = false;
            root.wantsInput = false;
        }
        onInputFocusedChanged: {
            if (inputFocused) {
                popup.visible = session.hasTranscript;
            } else {
                root.wantsInput = false;
                popup.visible = false;
            }
        }
    }

    function focusBar() {
        root.wantsInput = true;
        // The panel window gains focus only after the status change above is
        // processed, so the field is focused on the next event loop turn.
        Qt.callLater(function() {
            if (root.fullRepresentationItem) {
                root.fullRepresentationItem.takeFocus();
            }
        });
    }

    Connections {
        target: Plasmoid
        function onActivated() {
            if (root.inputInPopup) {
                popup.visible = !popup.visible;
            } else {
                root.focusBar();
            }
        }
    }
}
