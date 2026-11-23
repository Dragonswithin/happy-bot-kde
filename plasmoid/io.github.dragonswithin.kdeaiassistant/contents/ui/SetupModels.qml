/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * "AI model" section of ConfigSetup.qml: choose which configured model
 * answers, test or remove it, find model services running on this computer,
 * and add a hosted or other service by address.
 *
 * It keeps only transient state (what a scan found, the add-form fields, the
 * last test result). Everything durable goes through `page.save`. A model's
 * API key is typed here once and sent to the daemon; it is never read back.
 *
 * A model whose address is not on this computer is labelled as hosted with
 * the plain consequence: what the assistant reads is sent to that service.
 */
ColumnLayout {
    id: section

    required property var page

    readonly property var models: page.settings ? page.settings.models : ({})
    readonly property var modelNames: Object.keys(models).sort()
    readonly property string activeName: page.settings ? page.settings.active_model : ""
    // `models` and `activeName` update separately when settings reload, so the
    // name can briefly point at a model that is not in the map yet.
    readonly property var active: (activeName && models[activeName]) || null
    property var found: []
    property bool scanning: false
    property bool scanned: false
    property bool testing: false
    property string testResult: ""

    spacing: Kirigami.Units.smallSpacing

    function isLocal(address) {
        return /^https?:\/\/(127\.[0-9.]+|localhost|\[::1\])(:|\/|$)/.test(address || "");
    }

    function hostOf(address) {
        const match = (address || "").match(/^https?:\/\/([^\/:]+)/);
        return match ? match[1] : address;
    }

    function uniqueName(base) {
        let name = (base || "model").replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "").substring(0, 48) || "model";
        let candidate = name;
        for (let suffix = 2; section.models[candidate] !== undefined; suffix++) {
            candidate = name + "-" + suffix;
        }
        return candidate;
    }

    function addModel(name, entry) {
        section.page.save(function(settings) {
            settings.models[name] = entry;
            settings.active_model = name;
        }, function() {
            section.test(name);
        });
    }

    function test(name) {
        section.testing = true;
        section.testResult = i18n("Testing %1…", name);
        section.page.client.request("POST", "/models/test", { name: name }, function(data) {
            section.testing = false;
            section.testResult = data.tools
                ? i18n("%1 answers and can use tools. It is ready.", name)
                : i18n("%1 answers but did not use a tool. The assistant cannot act or search with it.", name);
        }, function(data) {
            section.testing = false;
            section.testResult = data.error || i18n("The test failed");
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

    Kirigami.Heading {
        level: 3
        text: i18n("AI model")
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: section.modelNames.length === 0
        wrapMode: Text.Wrap
        text: i18n("No model yet. Find one running on this computer, or add a service below.")
    }

    RowLayout {
        visible: section.modelNames.length > 0

        QQC2.ComboBox {
            id: chooser
            Layout.minimumWidth: Kirigami.Units.gridUnit * 14
            model: section.modelNames
            currentIndex: section.modelNames.indexOf(section.activeName)
            onActivated: section.page.save(function(settings) { settings.active_model = chooser.currentText; })
        }

        QQC2.Button {
            text: i18n("Test")
            icon.name: "system-run"
            enabled: section.activeName.length > 0 && !section.testing
            onClicked: section.test(section.activeName)
        }

        QQC2.Button {
            text: i18n("Remove")
            icon.name: "edit-delete"
            enabled: section.activeName.length > 0
            onClicked: {
                const name = section.activeName;
                section.testResult = "";
                section.page.save(function(settings) {
                    delete settings.models[name];
                    settings.active_model = Object.keys(settings.models).sort()[0] || "";
                });
            }
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: section.active !== null
        wrapMode: Text.Wrap
        opacity: 0.8
        text: section.active === null ? ""
            : section.isLocal(section.active.base_url)
                ? i18n("%1, running on this computer. Nothing leaves it.", section.active.model)
                : i18n("%1, hosted by %2. Whatever the assistant reads for a request, such as your clipboard or a file, is sent there.",
                       section.active.model, section.hostOf(section.active.base_url))
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: section.testResult.length > 0
        wrapMode: Text.Wrap
        text: section.testResult
    }

    RowLayout {
        QQC2.Button {
            text: i18n("Find models on this computer")
            icon.name: "edit-find"
            enabled: !section.scanning
            onClicked: section.scan()
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
        text: i18n("No model service is running on this computer.")
    }

    // One row per model that is ready to use now. A service that lists more
    // models than it has loaded (a catalogue) gets a switch to show them all.
    Repeater {
        model: section.found

        ColumnLayout {
            id: service

            required property var modelData
            property bool showAll: false
            readonly property var ready: modelData.models.filter(item => item.loaded)
            readonly property var others: modelData.models.filter(item => !item.loaded)

            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: service.showAll ? service.modelData.models : service.ready

                RowLayout {
                    id: offer

                    required property var modelData

                    Layout.fillWidth: true

                    QQC2.Label {
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        text: offer.modelData.loaded
                            ? i18n("%1 (port %2)", offer.modelData.id, service.modelData.port)
                            : i18n("%1 (port %2, not loaded)", offer.modelData.id, service.modelData.port)
                    }

                    QQC2.Button {
                        text: offer.modelData.configured_as ? i18n("Already added") : i18n("Use")
                        enabled: !offer.modelData.configured_as
                        onClicked: {
                            const entry = {
                                provider: "openai_compatible", base_url: service.modelData.base_url,
                                model: offer.modelData.id
                            };
                            if (offer.modelData.context_window > 0) {
                                entry.context_window = offer.modelData.context_window;
                            }
                            section.addModel(section.uniqueName(offer.modelData.id), entry);
                            section.found = [];
                            section.scanned = false;
                        }
                    }
                }
            }

            QQC2.CheckBox {
                visible: service.others.length > 0
                text: i18np("Also show %1 model the service on port %2 lists but has not loaded",
                            "Also show %1 models the service on port %2 lists but has not loaded",
                            service.others.length, service.modelData.port)
                checked: service.showAll
                onToggled: service.showAll = checked
            }
        }
    }

    Kirigami.Heading {
        level: 5
        text: i18n("Add a hosted or other service")
        topPadding: Kirigami.Units.smallSpacing
    }

    Kirigami.FormLayout {
        Layout.fillWidth: true

        QQC2.TextField {
            id: address
            Kirigami.FormData.label: i18n("Address:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 18
            placeholderText: "https://api.example.com/v1"
        }

        QQC2.TextField {
            id: modelId
            Kirigami.FormData.label: i18n("Model:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 18
            placeholderText: i18n("The model's id, as the service names it")
        }

        Kirigami.PasswordField {
            id: apiKey
            Kirigami.FormData.label: i18n("API key:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 18
            placeholderText: i18n("Leave empty if the service needs none")
        }

        QQC2.Button {
            text: i18n("Add")
            icon.name: "list-add"
            enabled: /^https?:\/\/.+/.test(address.text.trim()) && modelId.text.trim().length > 0
            onClicked: {
                section.addModel(section.uniqueName(modelId.text.trim()), {
                    provider: "openai_compatible", base_url: address.text.trim(),
                    model: modelId.text.trim(), api_key: apiKey.text
                });
                address.text = "";
                modelId.text = "";
                apiKey.text = "";
            }
        }
    }
}
