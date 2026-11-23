/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid

/**
 * "Assistant" page of the settings dialog: first-run setup and everything
 * the assistant itself is configured with (models, search tools, approvals,
 * folders). It is the graphical counterpart of the `kde-ai-assistant model`,
 * `tools`, `role`, `policy` and `folders` commands.
 *
 * Unlike the General page, nothing here is a Plasma `cfg_` value. The
 * settings belong to the daemon (src/kde_ai_assistant/settings.py); this page
 * reads them with `GET /settings` and every change is sent at once with
 * `PUT /settings`, which validates and applies it. `settings` is the
 * daemon's redacted copy: secrets arrive as null and are sent back as null,
 * which the daemon treats as "keep what is stored".
 *
 * The three sections (SetupModels.qml, SetupTools.qml, SetupBehavior.qml)
 * are Kirigami.FormLayouts linked with `twinFormLayouts`, so all their labels
 * share one column like a System Settings page. They receive this page as
 * their `page` property and use its `client`,
 * `settings`, `save` and `report`. `save(mutate, then)` copies the settings, lets `mutate` change
 * the copy, and sends it; on refusal the daemon's message is shown and the
 * local copy is left as it was.
 */
KCM.SimpleKCM {
    id: setupPage

    property var settings: null
    property var effectiveFolders: ({})
    property string message: ""
    property bool messageIsError: false
    property bool offline: false
    readonly property alias client: daemon

    DaemonClient {
        id: daemon
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
    }

    Component.onCompleted: reload()

    function report(text, isError) {
        setupPage.message = text || "";
        setupPage.messageIsError = isError === true;
    }

    function reload() {
        daemon.request("GET", "/settings", null, function(data) {
            setupPage.offline = false;
            setupPage.settings = data.settings;
            setupPage.effectiveFolders = data.effective_folders || {};
        }, function(data) {
            setupPage.offline = true;
            setupPage.report(data.error || i18n("The assistant is not running"), true);
        });
    }

    function save(mutate, then) {
        if (!setupPage.settings) {
            return;
        }
        const changed = JSON.parse(JSON.stringify(setupPage.settings));
        mutate(changed);
        daemon.request("PUT", "/settings", { settings: changed }, function(data) {
            setupPage.settings = data.settings;
            setupPage.report(i18n("Saved."), false);
            setupPage.reload();
            if (then) {
                then();
            }
        }, function(data) {
            setupPage.report(data.error || i18n("That could not be saved"), true);
        });
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: setupPage.message.length > 0
            text: setupPage.message
            type: setupPage.messageIsError ? Kirigami.MessageType.Error : Kirigami.MessageType.Positive
            showCloseButton: true
            onVisibleChanged: if (!visible) setupPage.message = ""
        }

        QQC2.Button {
            visible: setupPage.offline
            text: i18n("Try again")
            icon.name: "view-refresh"
            onClicked: setupPage.reload()
        }

        SetupModels {
            id: modelsSection
            Layout.fillWidth: true
            visible: setupPage.settings !== null
            page: setupPage
            twinFormLayouts: [toolsSection, behaviorSection]
        }

        SetupTools {
            id: toolsSection
            Layout.fillWidth: true
            visible: setupPage.settings !== null
            page: setupPage
            twinFormLayouts: [modelsSection, behaviorSection]
        }

        SetupBehavior {
            id: behaviorSection
            Layout.fillWidth: true
            visible: setupPage.settings !== null
            page: setupPage
            twinFormLayouts: [modelsSection, toolsSection]
        }
    }
}
