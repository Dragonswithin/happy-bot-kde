/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: root

    property string daemonUrl: "http://127.0.0.1:19000"
    property string transcript: i18n("Ready.")
    property string statusText: i18n("Starting")
    property string contextKind: "combined"
    property bool busy: false

    signal statusChanged(string status)
    signal summaryChanged(string summary)

    Layout.minimumWidth: Kirigami.Units.gridUnit * 22
    Layout.preferredWidth: Kirigami.Units.gridUnit * 28
    Layout.minimumHeight: Kirigami.Units.gridUnit * 30
    collapseMarginsHint: true

    Component.onCompleted: refreshStatus()

    Timer {
        interval: 12000
        repeat: true
        running: true
        onTriggered: root.refreshStatus()
    }

    function appendLine(prefix, text) {
        if (root.transcript === i18n("Ready.")) {
            root.transcript = "";
        }
        root.transcript += (root.transcript ? "\n\n" : "") + prefix + "\n" + text;
    }

    function setStatus(status, summary) {
        root.statusText = summary;
        root.statusChanged(status);
        root.summaryChanged(summary);
    }

    function request(method, path, payload, onSuccess, onFailure) {
        const xhr = new XMLHttpRequest();
        xhr.open(method, root.daemonUrl + path);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return;
            }
            let data = {};
            try {
                data = JSON.parse(xhr.responseText || "{}");
            } catch (error) {
                data = { ok: false, error: "Invalid daemon response" };
            }
            if (xhr.status >= 200 && xhr.status < 300 && data.ok !== false) {
                onSuccess(data);
            } else if (onFailure) {
                onFailure(data);
            }
        };
        xhr.onerror = function() {
            if (onFailure) {
                onFailure({ ok: false, error: "Desktop daemon is not reachable" });
            }
        };
        xhr.send(payload ? JSON.stringify(payload) : null);
    }

    function refreshStatus() {
        request("GET", "/health", null, function(data) {
            const status = data.status || "idle";
            const summary = data.full_ui_url
                ? i18n("Ready as %1", data.user || "")
                : i18n("Ready");
            setStatus(status, summary);
        }, function(data) {
            setStatus("offline", data.error || i18n("Desktop daemon is offline"));
        });
    }

    function newChat() {
        transcript = i18n("Ready.");
        prompt.text = "";
        contextKind = "combined";
        refreshStatus();
    }

    function showSettings() {
        appendLine(i18n("Settings"), i18n("Daemon URL: %1", root.daemonUrl));
    }

    function askClipboard() {
        contextKind = "clipboard";
        if (!prompt.text.trim()) {
            prompt.text = i18n("Use my clipboard as context and help me with it.");
        }
        ask();
    }

    function askWindow() {
        contextKind = "window";
        if (!prompt.text.trim()) {
            prompt.text = i18n("Use my active window as context and help me with it.");
        }
        ask();
    }

    function ask() {
        const message = prompt.text.trim();
        if (!message || busy) {
            return;
        }
        busy = true;
        setStatus("thinking", i18n("Thinking"));
        appendLine(i18n("You"), message);
        prompt.text = "";
        request("POST", "/ask", { message: message, contextKind: contextKind }, function(data) {
            busy = false;
            setStatus("idle", i18n("Ready"));
            appendLine(i18n("Assistant"), data.answer || i18n("No answer returned."));
        }, function(data) {
            busy = false;
            setStatus("offline", data.error || i18n("Request failed"));
            appendLine(i18n("Error"), data.error || i18n("Request failed"));
        });
    }

    function openFullUi() {
        request("POST", "/open-full-ui", { open: false }, function(data) {
            if (data.url) {
                Qt.openUrlExternally(data.url);
            }
        }, function(data) {
            appendLine(i18n("Error"), data.error || i18n("Could not open the full assistant UI."));
        });
    }

    function openOpenChamber() {
        openFullUi();
    }

    function screenshotContext() {
        request("POST", "/screenshot", {}, function(data) {
            appendLine(i18n("Screenshot"), data.path ? i18n("Saved transient context screenshot: %1", data.path) : i18n("Screenshot captured."));
        }, function(data) {
            appendLine(i18n("Error"), data.error || i18n("Screenshot failed."));
        });
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true

            Kirigami.Icon {
                source: "assistant"
                implicitWidth: Kirigami.Units.iconSizes.medium
                implicitHeight: Kirigami.Units.iconSizes.medium
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                PlasmaExtras.Heading {
                    Layout.fillWidth: true
                    level: 3
                    text: i18n("AI Assistant")
                    elide: Text.ElideRight
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: root.statusText
                    opacity: 0.75
                    elide: Text.ElideRight
                }
            }

            QQC2.BusyIndicator {
                running: root.busy
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
        }

        PlasmaComponents3.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            QQC2.TextArea {
                text: root.transcript
                readOnly: true
                wrapMode: Text.Wrap
                selectByMouse: true
            }
        }

        RowLayout {
            Layout.fillWidth: true

            PlasmaComponents3.Button {
                text: i18n("Clipboard")
                icon.name: "edit-paste"
                onClicked: root.askClipboard()
            }

            PlasmaComponents3.Button {
                text: i18n("Window")
                icon.name: "window"
                onClicked: root.askWindow()
            }

            PlasmaComponents3.Button {
                text: i18n("Screenshot")
                icon.name: "spectacle"
                onClicked: root.screenshotContext()
            }

            Item {
                Layout.fillWidth: true
            }

            PlasmaComponents3.Button {
                icon.name: "internet-web-browser"
                text: i18n("Open")
                onClicked: root.openFullUi()
            }
        }

        QQC2.TextArea {
            id: prompt
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 5
            wrapMode: Text.Wrap
            placeholderText: i18n("Ask anything, or use Clipboard/Window for context")
            enabled: !root.busy
            Keys.onPressed: event => {
                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                    root.ask();
                    event.accepted = true;
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            PlasmaComponents3.Button {
                text: i18n("New")
                icon.name: "document-new"
                onClicked: root.newChat()
            }

            Item {
                Layout.fillWidth: true
            }

            PlasmaComponents3.Button {
                text: i18n("Ask")
                icon.name: "go-next"
                enabled: !root.busy && prompt.text.trim().length > 0
                onClicked: root.ask()
            }
        }
    }
}
