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
 * Visually it is the status line: a message strip for the last outcome, a
 * "Try again" button while the daemon cannot be reached, and "Check
 * everything", which runs the daemon's self-check (`GET /check`,
 * src/happy_bot/self_check.py) and lists any problem with its fix.
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
    property bool checking: false
    readonly property bool ready: settings !== null
    readonly property alias client: daemon

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

    /** Runs the daemon's self-check and shows the problems (and fixes), or that all is well. */
    function check() {
        store.checking = true;
        daemon.request("GET", "/check", null, function(data) {
            store.checking = false;
            const problems = data.checks.filter(item => !item.ok);
            store.report(problems.length === 0 ? i18n("Everything works.")
                : problems.map(item => item.name + ": " + item.detail + " " + item.fix).join("\n"), problems.length > 0);
        }, function(data) {
            store.checking = false;
            store.report(data.error || i18n("The check could not run"), true);
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

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            visible: store.offline
            text: i18n("Try again")
            icon.name: "view-refresh"
            onClicked: store.reload()
        }

        QQC2.Button {
            visible: !store.offline
            text: i18n("Check everything")
            icon.name: "checkmark"
            enabled: !store.checking
            onClicked: store.check()
        }

        QQC2.BusyIndicator {
            running: store.checking
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }
}
