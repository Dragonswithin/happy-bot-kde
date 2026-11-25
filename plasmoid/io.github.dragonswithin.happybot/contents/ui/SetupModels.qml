/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The AI Model page (ConfigModels.qml): the user's AIs in the order they
 * are asked, and three ways to add one.
 *
 * - The list follows `model_order` (src/happy_bot/settings.py): the first
 *   AI answers, and when it fails the next one does (src/happy_bot/ask_stream.py).
 *   Each row shows where the AI runs (this computer, with its port, or
 *   online and where) and whether it sees pictures (`vision`), arrows to move it up or down, Test (the full
 *   compatibility check, `POST /models/check`, src/happy_bot/model_check.py,
 *   summarised as passed, works-with-a-note or a problem), Remove, and
 *   "Settings", which opens that AI's own settings under it
 *   (ModelDetails.qml). Moving one keeps `active_model` equal to the first.
 * - "Find on this computer" (`POST /models/discover`) lists the models local
 *   services have loaded; each can be put first or added to the end.
 * - "Online service…" opens OnlineModelChooser.qml: pick the service, get
 *   and paste a key with directions, pick a model.
 * - "By hand…": an address, model id and optional key, for any other
 *   OpenAI-compatible service, self-hosted or not.
 *
 * Every addition goes through `POST /models/use`
 * (src/happy_bot/model_setup.py), which adds the model, places it, tests it
 * and removes it again if it does not answer. Reordering, removing and the
 * per-AI settings use `page.save` (DaemonSettings.qml).
 *
 * Only transient state lives here: what a scan found, which rows are open,
 * the by-hand fields, the last test result and this month's costs. A key
 * typed here is sent once and never read back.
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
    readonly property var order: (page.settings && page.settings.model_order) || []
    property var costs: ({})
    property string testedName: ""
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


    function readCosts() {
        section.page.client.request("GET", "/spend", null, data => section.costs = data.models || {}, () => {});
    }

    function costOf(name) {
        const entry = section.costs[name];
        return entry && entry.cost > 0 ? Number(entry.cost).toFixed(2) : "";
    }

    /** Moves `name` by `delta` places in the order; the first one is the one that answers. */
    function move(name, delta) {
        section.page.save(function(settings) {
            const order = settings.model_order.slice();
            const from = order.indexOf(name);
            const to = Math.max(0, Math.min(order.length - 1, from + delta));
            order.splice(from, 1);
            order.splice(to, 0, name);
            settings.model_order = order;
            settings.active_model = order[0];
        });
    }

    function remove(name) {
        section.testResult = "";
        section.page.save(function(settings) {
            delete settings.models[name];
            settings.model_order = settings.model_order.filter(other => other !== name);
            settings.active_model = settings.model_order[0] || "";
        });
    }

    Component.onCompleted: readCosts()

    function showResult(passed, text) {
        section.testPassed = passed;
        section.testResult = text;
    }

    /** Adds a model through the daemon, which tests and places it; `job` is "main" (first) or "none" (last). */
    function use(body, job, key) {
        section.testedName = "";
        section.usingKey = key || "";
        section.page.client.request("POST", "/models/use", Object.assign({ job: job }, body), function(data) {
            section.usingKey = "";
            section.page.settings = data.settings;
            section.showResult(data.passed !== false, data.message);
            section.page.reload();
        }, function(data) {
            section.usingKey = "";
            section.showResult(false, data.error || i18n("That did not work"));
        });
    }

    function test(name) {
        section.testedName = name;
        section.testing = true;
        section.testResult = "";
        // The full compatibility check (src/happy_bot/model_check.py): a few small requests.
        section.page.client.request("POST", "/models/check", { name: name }, function(data) {
            section.testing = false;
            section.showResult(data.passed === true, data.message);
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

    // --- the AIs, in the order they are asked ---------------------------------
    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Your AIs, in the order they are asked")
    }

    QQC2.Label {
        visible: section.order.length === 0
        text: i18n("No AI yet. Add one below: one on this computer, or an online service.")
        wrapMode: Text.Wrap
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
    }

    QQC2.Label {
        visible: section.order.length > 0
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("The first AI answers. If it does not, the next one does, and so on. Use the arrows to change the order.")
    }

    // Repeated rows go inside one column: a Repeater placed directly in a
    // FormLayout can insert its rows after later siblings.
    ColumnLayout {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 34
        visible: section.order.length > 0
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: section.order

            ColumnLayout {
                id: row

                required property int index
                required property string modelData
                readonly property var entry: section.models[modelData] || null
                readonly property bool local: entry !== null && section.isLocal(entry.base_url)
                property bool open: false

                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Label {
                        text: i18n("%1.", row.index + 1)
                        font.weight: Font.Bold
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 1.5
                    }

                    Kirigami.Icon {
                        source: row.local ? "computer" : "network-workgroup"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: row.modelData
                            elide: Text.ElideMiddle
                            font.weight: row.index === 0 ? Font.Bold : Font.Normal
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                            text: row.entry === null ? ""
                                : (row.local ? i18n("On this computer, port %1", (row.entry.base_url.match(/:(\d+)/) || ["", "?"])[1])
                                             : i18n("Online at %1", section.hostOf(row.entry.base_url)))
                                  + (row.entry.vision ? i18n(" · sees pictures") : "")
                                  + (row.entry.hand_over_long ? i18n(" · hands long requests on") : "")
                        }
                    }

                    QQC2.ToolButton {
                        icon.name: "arrow-up"
                        text: i18n("Ask %1 earlier", row.modelData)
                        display: QQC2.AbstractButton.IconOnly
                        enabled: row.index > 0
                        QQC2.ToolTip.text: i18n("Move up")
                        QQC2.ToolTip.visible: hovered
                        onClicked: section.move(row.modelData, -1)
                    }

                    QQC2.ToolButton {
                        icon.name: "arrow-down"
                        text: i18n("Ask %1 later", row.modelData)
                        display: QQC2.AbstractButton.IconOnly
                        enabled: row.index < section.order.length - 1
                        QQC2.ToolTip.text: i18n("Move down")
                        QQC2.ToolTip.visible: hovered
                        onClicked: section.move(row.modelData, 1)
                    }

                    QQC2.Button {
                        text: i18n("Test")
                        enabled: !section.testing
                        onClicked: section.test(row.modelData)
                    }

                    QQC2.Button {
                        text: i18n("Settings")
                        icon.name: "configure"
                        checkable: true
                        checked: row.open
                        onToggled: row.open = checked
                    }

                    QQC2.ToolButton {
                        icon.name: "edit-delete"
                        text: i18n("Remove %1", row.modelData)
                        display: QQC2.AbstractButton.IconOnly
                        QQC2.ToolTip.text: i18n("Remove this AI")
                        QQC2.ToolTip.visible: hovered
                        onClicked: section.remove(row.modelData)
                    }
                }

                RowLayout {
                    visible: section.testedName === row.modelData && (section.testing || section.testResult.length > 0)
                    Layout.leftMargin: Kirigami.Units.gridUnit * 2

                    QQC2.BusyIndicator {
                        running: section.testing
                        visible: running
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    }

                    Kirigami.InlineMessage {
                        Layout.fillWidth: true
                        visible: !section.testing && section.testResult.length > 0
                        type: section.testPassed ? Kirigami.MessageType.Positive : Kirigami.MessageType.Warning
                        text: section.testResult
                    }
                }

                Loader {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 2
                    active: row.open
                    visible: active
                    sourceComponent: ModelDetails {
                        page: section.page
                        name: row.modelData
                        online: !row.local
                        spent: section.costOf(row.modelData)
                    }
                }

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: row.index < section.order.length - 1
                    opacity: 0.5
                }
            }
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        visible: section.testedName === "" && section.testResult.length > 0
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
                            : offer.modelData.configured_as ? "listed" : ""

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
                            text: offer.job === "" ? i18n("Add to the list") : i18n("In the list")
                            enabled: offer.job === "" && section.usingKey === ""
                            onClicked: section.use({ base_url: service.modelData.base_url, model: offer.modelData.id },
                                                   "none", offer.key)
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
