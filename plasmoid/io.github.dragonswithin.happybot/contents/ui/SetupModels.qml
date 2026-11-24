/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The top of the AI Model page (ConfigModels.qml), written as two plain
 * questions and three ways to add an AI:
 *
 * - "Ask first": the model that answers (`active_model`), with Test and
 *   Remove, and a line saying whether what it reads stays on this computer.
 * - "If it fails, ask": the model that answers when the first one does not
 *   (`agent.fallback_model`). Only models on this computer are offered, so
 *   nothing goes online unless an online model is chosen to ask first
 *   (src/happy_bot/ask_stream.py enforces the same rule).
 * - "Find on this computer" (`POST /models/discover`) lists the models local
 *   services have loaded; each can be made the one asked first or the backup
 *   with one press.
 * - "Online service…" opens OnlineModelChooser.qml: pick the service, get
 *   and paste a key with directions, pick a model.
 * - "By hand…": an address, model id and optional key, for any other
 *   OpenAI-compatible service, self-hosted or not.
 *
 * Every addition goes through `POST /models/use`
 * (src/happy_bot/model_setup.py), which adds the model, gives it its job and
 * tests it, and removes it again if it does not answer; the result is shown
 * here. Choosing between models already added uses `page.save`
 * (DaemonSettings.qml). Model details (address, context window, prices) and
 * the quicker-model and spending options are below, in ModelDetails.qml.
 *
 * Only transient state lives here: what a scan found, the by-hand fields,
 * the last test result. A key typed here is sent once and never read back.
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property var models: page.settings ? page.settings.models : ({})
    readonly property var modelNames: Object.keys(models).sort()
    readonly property string activeName: page.settings ? page.settings.active_model : ""
    // `models` and `activeName` update separately when settings reload, so the
    // name can briefly point at a model that is not in the map yet.
    readonly property var active: (activeName && models[activeName]) || null
    readonly property string backupName: (page.settings && page.settings.agent && page.settings.agent.fallback_model) || ""
    readonly property var backupChoices: [""].concat(modelNames.filter(name => name !== activeName
                                                                           && isLocal(models[name].base_url)))
    property var found: []
    property bool scanning: false
    property bool scanned: false
    property bool testing: false
    property string testResult: ""
    property bool testPassed: false
    property string adding: ""   // "", "online" or "manual": which add form is open
    property string usingKey: ""  // the found model being added, while its test runs

    function isLocal(address) {
        return /^https?:\/\/(127\.[0-9.]+|localhost|\[::1\])(:|\/|$)/.test(address || "");
    }

    function hostOf(address) {
        const match = (address || "").match(/^https?:\/\/([^\/:]+)/);
        return match ? match[1] : address;
    }

    function describe(name) {
        const model = section.models[name];
        if (!model) {
            return name;
        }
        const port = (model.base_url || "").match(/:(\d+)(\/|$)/);
        if (section.isLocal(model.base_url)) {
            // Two local services can serve similar models; the port tells them apart.
            return port ? i18n("%1 (on this computer, port %2)", name, port[1]) : i18n("%1 (on this computer)", name);
        }
        return i18n("%1 (online, %2)", name, section.hostOf(model.base_url));
    }

    function showResult(passed, text) {
        section.testPassed = passed;
        section.testResult = text;
    }

    /** Adds a model through the daemon, which tests it; `job` is "main", "backup" or "none". */
    function use(body, job, key) {
        section.usingKey = key || "";
        section.page.client.request("POST", "/models/use", Object.assign({ job: job }, body), function(data) {
            section.usingKey = "";
            section.page.settings = data.settings;
            section.showResult(data.tools, data.message);
            section.page.reload();
        }, function(data) {
            section.usingKey = "";
            section.showResult(false, data.error || i18n("That did not work"));
        });
    }

    function test(name) {
        section.testing = true;
        section.testResult = "";
        section.page.client.request("POST", "/models/test", { name: name }, function(data) {
            section.testing = false;
            section.showResult(data.tools === true, data.tools
                ? i18n("%1 answers and can use tools. It is ready.", name)
                : i18n("%1 answers but did not use a tool, so Happy Bot cannot search or act with it.", name));
        }, function(data) {
            section.testing = false;
            section.showResult(false, data.error || i18n("The test failed"));
        });
    }

    function scan() {
        section.scanning = true;
        section.page.client.request("POST", "/models/discover", {}, function(data) {
            section.scanning = false;
            section.scanned = true;
            section.found = data.services || [];
        }, function(data) {
            section.scanning = false;
            section.page.report(data.error || i18n("Could not look for models"), true);
        });
    }

    // --- which AI answers ------------------------------------------------------
    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Which AI answers")
    }

    QQC2.Label {
        Kirigami.FormData.label: i18n("Ask first:")
        visible: section.modelNames.length === 0
        text: i18n("No AI yet. Add one below: one on this computer, or an online service.")
        wrapMode: Text.Wrap
        Layout.maximumWidth: Kirigami.Units.gridUnit * 20
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Ask first:")
        visible: section.modelNames.length > 0
        spacing: Kirigami.Units.smallSpacing

        QQC2.ComboBox {
            id: mainBox
            Layout.minimumWidth: Kirigami.Units.gridUnit * 16
            model: section.modelNames.map(name => section.describe(name))
            currentIndex: section.modelNames.indexOf(section.activeName)
            onActivated: index => {
                const name = section.modelNames[index];
                section.page.save(function(settings) {
                    settings.active_model = name;
                    if (settings.agent.fallback_model === name) {
                        settings.agent.fallback_model = "";
                    }
                });
            }
        }

        QQC2.Button {
            text: i18n("Test")
            icon.name: "media-playback-start"
            enabled: section.activeName.length > 0 && !section.testing
            onClicked: section.test(section.activeName)
        }

        QQC2.ToolButton {
            icon.name: "edit-delete"
            text: i18n("Remove this AI")
            display: QQC2.AbstractButton.IconOnly
            enabled: section.activeName.length > 0
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
            onClicked: {
                const name = section.activeName;
                section.testResult = "";
                section.page.save(function(settings) {
                    delete settings.models[name];
                    for (const key of ["fallback_model", "quick_model"]) {
                        if (settings.agent[key] === name) {
                            settings.agent[key] = "";
                        }
                    }
                    settings.active_model = Object.keys(settings.models).sort()[0] || "";
                });
            }
        }

        QQC2.BusyIndicator {
            running: section.testing
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }

    RowLayout {
        visible: section.active !== null
        spacing: Kirigami.Units.smallSpacing
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24

        Kirigami.Icon {
            source: section.active && section.isLocal(section.active.base_url) ? "computer" : "network-workgroup"
            Layout.preferredWidth: Kirigami.Units.iconSizes.small
            Layout.preferredHeight: Kirigami.Units.iconSizes.small
            Layout.alignment: Qt.AlignTop
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.8
            text: section.active === null ? ""
                : section.isLocal(section.active.base_url)
                    ? i18n("It runs on this computer. Nothing leaves it.")
                    : i18n("It is online at %1. Whatever Happy Bot reads for a request, such as your clipboard or a file, is sent there.",
                           section.hostOf(section.active.base_url))
        }
    }

    QQC2.ComboBox {
        id: backupBox
        Kirigami.FormData.label: i18n("If it fails, ask:")
        visible: section.modelNames.length > 0
        Layout.minimumWidth: Kirigami.Units.gridUnit * 16
        model: section.backupChoices.map(name => name === "" ? i18n("Nobody (show what went wrong)") : section.describe(name))
        currentIndex: Math.max(0, section.backupChoices.indexOf(section.backupName))
        onActivated: index => {
            const wanted = section.backupChoices[index];
            section.page.save(function(settings) { settings.agent.fallback_model = wanted; });
        }
    }

    QQC2.Label {
        visible: section.modelNames.length > 0
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("If the first AI does not answer, this one answers instead. Only an AI on this computer can step in, so nothing goes online unless you choose an online AI to ask first.")
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        visible: section.testResult.length > 0
        type: section.testPassed ? Kirigami.MessageType.Positive : Kirigami.MessageType.Warning
        text: section.testResult
    }

    // --- adding an AI ------------------------------------------------------------
    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Add an AI")
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            text: i18n("Find on this computer")
            icon.name: "edit-find"
            enabled: !section.scanning
            onClicked: {
                section.adding = "";
                section.scan();
            }
        }

        QQC2.Button {
            text: i18n("Online service…")
            icon.name: "network-workgroup"
            checkable: true
            checked: section.adding === "online"
            onToggled: section.adding = checked ? "online" : ""
        }

        QQC2.Button {
            text: i18n("By hand…")
            icon.name: "document-edit"
            checkable: true
            checked: section.adding === "manual"
            onToggled: section.adding = checked ? "manual" : ""
        }

        QQC2.BusyIndicator {
            running: section.scanning
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }

    QQC2.Label {
        visible: section.scanned && section.found.length === 0
        text: i18n("No AI service is running on this computer.")
        opacity: 0.8
    }

    ColumnLayout {
        visible: section.found.length > 0
        spacing: Kirigami.Units.smallSpacing

        // One row per model a local service has loaded. A service that lists more
        // models than it has loaded (a catalogue) gets a switch to show them all.
        Repeater {
            model: section.found

            ColumnLayout {
                id: service

                required property var modelData
                property bool showAll: false
                readonly property var others: modelData.models.filter(item => !item.loaded)

                spacing: 0

                Repeater {
                    model: service.showAll ? service.modelData.models : service.modelData.models.filter(item => item.loaded)

                    RowLayout {
                        id: offer

                        required property var modelData
                        readonly property string key: service.modelData.base_url + "|" + modelData.id
                        readonly property string job: offer.modelData.configured_as === section.activeName ? "main"
                            : offer.modelData.configured_as && offer.modelData.configured_as === section.backupName ? "backup" : ""

                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: "computer"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        }

                        ColumnLayout {
                            spacing: 0
                            Layout.minimumWidth: Kirigami.Units.gridUnit * 11
                            Layout.maximumWidth: Kirigami.Units.gridUnit * 14

                            QQC2.Label {
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                text: offer.modelData.id
                                opacity: offer.modelData.loaded ? 1 : 0.6
                            }

                            QQC2.Label {
                                text: offer.modelData.loaded ? i18n("port %1", service.modelData.port) : i18n("not loaded")
                                font: Kirigami.Theme.smallFont
                                opacity: 0.6
                            }
                        }

                        QQC2.Button {
                            text: offer.job === "main" ? i18n("Asked first") : i18n("Ask first")
                            enabled: offer.job !== "main" && section.usingKey === ""
                            onClicked: section.use({ base_url: service.modelData.base_url, model: offer.modelData.id },
                                                   "main", offer.key)
                        }

                        QQC2.Button {
                            text: offer.job === "backup" ? i18n("Is the backup") : i18n("Use if it fails")
                            enabled: offer.job === "" && section.usingKey === "" && section.modelNames.length > 0
                            onClicked: section.use({ base_url: service.modelData.base_url, model: offer.modelData.id },
                                                   "backup", offer.key)
                        }

                        QQC2.BusyIndicator {
                            running: section.usingKey === offer.key
                            visible: running
                            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        }
                    }
                }

                QQC2.CheckBox {
                    visible: service.others.length > 0
                    text: i18np("Show %1 more model this service can load", "Show %1 more models this service can load",
                                service.others.length)
                    checked: service.showAll
                    onToggled: service.showAll = checked
                }
            }
        }
    }

    Loader {
        Layout.fillWidth: true
        active: section.adding === "online"
        visible: active
        sourceComponent: OnlineModelChooser {
            page: section.page
            onAdded: (name, message) => {
                section.showResult(true, message);
                section.adding = "";
                section.page.reload();
            }
        }
    }

    QQC2.Label {
        visible: section.adding === "manual"
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        text: i18n("For any other service that speaks the OpenAI chat API, on this computer, your network or online.")
    }

    QQC2.TextField {
        id: address
        Kirigami.FormData.label: i18n("Address:")
        visible: section.adding === "manual"
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        placeholderText: "https://api.example.com/v1"
    }

    QQC2.TextField {
        id: modelId
        Kirigami.FormData.label: i18n("Model:")
        visible: section.adding === "manual"
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        placeholderText: i18n("The model's id, as the service names it")
    }

    Kirigami.PasswordField {
        id: apiKey
        Kirigami.FormData.label: i18n("API key:")
        visible: section.adding === "manual"
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        placeholderText: i18n("Leave empty if the service needs none")
    }

    QQC2.CheckBox {
        id: manualFirst
        visible: section.adding === "manual"
        text: i18n("Ask this one first")
        checked: true
    }

    QQC2.Button {
        visible: section.adding === "manual"
        text: section.usingKey === "manual" ? i18n("Adding and testing…") : i18n("Add and test")
        icon.name: "list-add"
        enabled: section.usingKey === "" && /^https?:\/\/.+/.test(address.text.trim()) && modelId.text.trim().length > 0
        onClicked: {
            section.use({ base_url: address.text.trim(), model: modelId.text.trim(), api_key: apiKey.text },
                        manualFirst.checked ? "main" : "none", "manual");
            apiKey.text = "";
        }
    }
}
