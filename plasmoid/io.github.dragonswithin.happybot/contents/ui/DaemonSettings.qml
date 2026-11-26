/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid

/**
 * The settings the daemon stores (src/happy_bot/settings.py), loaded
 * for one page of the applet's settings dialog, with the page's status line.
 *
 * Every daemon-backed page (ConfigModels.qml, ConfigTools.qml,
 * ConfigBehavior.qml, ConfigHistory.qml) puts one of these at the top of its
 * column and hands it to its sections as their `page`. Sections read
 * `settings`, change them through `save`, show outcomes through `report`, and
 * make other requests through `client`.
 *
 * `settings` is the daemon's redacted copy (`GET /settings`): secrets arrive
 * as null and are sent back as null, which the daemon treats as "keep what is
 * stored". Three read-only values come with it: `effectiveFolders` (where
 * each standard folder is now), `terminals` (installed terminals the
 * assistant can open) and `suggestedInstructions` (the default text of the
 * user's instructions).
 *
 * `save(mutate, then)` copies the settings, lets `mutate` change the copy and
 * sends the whole copy with `PUT /settings`, which validates and applies it at
 * once; there is no Apply step. On refusal the daemon's message is shown and
 * the local copy stays as it was, so the controls snap back. After any save
 * the settings are read again, so other changes show up.
 *
 * The status strip appears while loading and when there is feedback to show.
 * ConfigTools.qml groups the app-wide self-check with the connections it tests.
 */
ColumnLayout {
    id: store

    property var settings: null
    property var effectiveFolders: ({})
    property var terminals: []
    property string suggestedInstructions: ""
    property string message: ""
    property bool messageIsError: false
    property bool offline: false
    readonly property bool ready: settings !== null
    readonly property alias client: daemon

    visible: !ready || offline || message.length > 0
    spacing: Kirigami.Units.smallSpacing

    DaemonClient {
        id: daemon
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
    }

    Component.onCompleted: reload()

    function report(text, isError) {
        store.message = text || "";
        store.messageIsError = isError === true;
    }

    function reload() {
        daemon.request("GET", "/settings", null, function(data) {
            if (store.offline) store.report("", false);
            store.offline = false;
            store.settings = data.settings;
            store.effectiveFolders = data.effective_folders || {};
            store.terminals = data.terminals || [];
            store.suggestedInstructions = data.suggested_instructions || "";
        }, function(data) {
            store.offline = true;
            store.report(data.error || i18n("The assistant is not running"), true);
        });
    }

    function save(mutate, then) {
        if (!store.settings) {
            return;
        }
        const changed = JSON.parse(JSON.stringify(store.settings));
        mutate(changed);
        daemon.request("PUT", "/settings", { settings: changed }, function(data) {
            store.settings = data.settings;
            store.report(i18n("Saved."), false);
            store.reload();
            if (then) {
                then();
            }
        }, function(data) {
            store.report(data.error || i18n("That could not be saved"), true);
            // Rebind controls that already show the refused value.
            store.settings = JSON.parse(JSON.stringify(store.settings));
        });
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: store.message.length > 0
        text: store.message
        type: store.messageIsError ? Kirigami.MessageType.Error : Kirigami.MessageType.Positive
        showCloseButton: true
        onVisibleChanged: if (!visible) store.message = ""
    }

    QQC2.Button {
        visible: store.offline
        text: i18n("Try again")
        icon.name: "view-refresh"
        onClicked: store.reload()
    }

    RowLayout {
        visible: !store.ready && !store.offline
        QQC2.BusyIndicator {
            running: parent.visible
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
        QQC2.Label { text: i18n("Loading settings…") }
    }
}
