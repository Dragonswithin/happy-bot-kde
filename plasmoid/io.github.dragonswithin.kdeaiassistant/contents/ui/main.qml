/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtCore as QtCore

import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

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
    property string assistantStatus: "starting"
    property string lastSummary: "Starting desktop bridge"

    Plasmoid.icon: "assistant"
    Plasmoid.status: assistantStatus === "thinking" || assistantStatus === "needs_approval"
        ? PlasmaCore.Types.ActiveStatus
        : PlasmaCore.Types.PassiveStatus
    Plasmoid.title: i18n("KDE AI Assistant")
    toolTipSubText: lastSummary

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
        status: root.assistantStatus
    }

    fullRepresentation: FullRepresentation {
        daemonUrl: root.daemonUrl
        onStatusChanged: status => {
            root.assistantStatus = status;
        }
        onSummaryChanged: summary => {
            root.lastSummary = summary;
        }
    }

    function showAndRun(callbackName) {
        root.expanded = true;
        if (root.fullRepresentationItem && root.fullRepresentationItem[callbackName]) {
            root.fullRepresentationItem[callbackName]();
        }
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("New Chat")
            icon.name: "document-new"
            onTriggered: root.showAndRun("newChat")
        },
        PlasmaCore.Action {
            text: i18n("Ask About Clipboard")
            icon.name: "edit-paste"
            onTriggered: root.showAndRun("askClipboard")
        },
        PlasmaCore.Action {
            text: i18n("Ask About Active Window")
            icon.name: "window"
            onTriggered: root.showAndRun("askWindow")
        },
        PlasmaCore.Action {
            text: i18n("Open Full Assistant")
            icon.name: "internet-web-browser"
            onTriggered: root.showAndRun("openFullUi")
        },
        PlasmaCore.Action {
            text: i18n("Settings")
            icon.name: "configure"
            onTriggered: root.showAndRun("showSettings")
        }
    ]
}
