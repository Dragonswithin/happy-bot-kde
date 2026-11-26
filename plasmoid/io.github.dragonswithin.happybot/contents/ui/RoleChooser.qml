/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The one-press setup for a search job (`role`: `file_search` or
 * `web_search`), shown under that job's row in SetupTools.qml when the user
 * presses "Set up". It is the easy route; RoleEditor.qml stays as the
 * by-hand one.
 *
 * When shown it asks the daemon what can do the job (`POST /search/choices`,
 * src/happy_bot/search_choices.py) and lists the choices best first, the
 * recommended one marked. Each says in plain words what it does, where the
 * user's words would go, and anything missing (a program to install). A
 * choice that needs an address or a key shows a field for it, with a link
 * to where to get one. "Use this" sends `POST /search/use`
 * (src/happy_bot/search_setup.py), which adds the tool, gives it the job
 * and runs a test search; it can take a minute the first time, so the
 * section shows that it is busy. On success the page's settings are
 * replaced with the daemon's and `done()` is emitted; on failure the reason
 * is shown under that choice and nothing has changed.
 *
 * It holds only transient state: the choices, typed inputs and which
 * choice is being set up. Typed keys go to the daemon once and are never
 * read back.
 */
ColumnLayout {
    id: chooser

    required property var page
    required property string role

    property var choices: []
    property bool loading: true
    property string usingId: ""
    property var errors: ({})
    property var typed: ({})

    signal done()

    spacing: Kirigami.Units.largeSpacing

    function load() {
        chooser.loading = true;
        chooser.page.client.request("POST", "/search/choices", { role: chooser.role }, function(data) {
            chooser.loading = false;
            chooser.choices = data.choices || [];
            const typed = {};
            for (const choice of chooser.choices) {
                for (const field of choice.inputs) {
                    typed[choice.id + "/" + field.name] = field.value || "";
                }
            }
            chooser.typed = typed;
        }, function(data) {
            chooser.loading = false;
            chooser.page.report(data.error || i18n("Could not look for search tools"), true);
        });
    }

    function filled(choice) {
        return choice.inputs.every(field => String(chooser.typed[choice.id + "/" + field.name] || "").trim().length > 0);
    }

    function use(choice) {
        const inputs = {};
        for (const field of choice.inputs) {
            inputs[field.name] = String(chooser.typed[choice.id + "/" + field.name] || "").trim();
        }
        chooser.usingId = choice.id;
        chooser.errors = Object.assign({}, chooser.errors, { [choice.id]: "" });
        chooser.page.client.request("POST", "/search/use", { role: chooser.role, choice: choice.id, inputs: inputs }, function(data) {
            chooser.usingId = "";
            chooser.page.settings = data.settings;
            chooser.page.report(chooser.role === "file_search"
                ? i18n("File search is set up with %1. It works.", choice.title)
                : i18n("Web search is set up with %1. It works.", choice.title), false);
            chooser.page.reload();
            chooser.done();
        }, function(data) {
            chooser.usingId = "";
            chooser.errors = Object.assign({}, chooser.errors, { [choice.id]: data.error || i18n("That did not work") });
        });
    }

    Component.onCompleted: load()

    RowLayout {
        visible: chooser.loading
        spacing: Kirigami.Units.smallSpacing

        QQC2.BusyIndicator {
            running: chooser.loading
            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
        }

        QQC2.Label {
            text: chooser.role === "file_search"
                ? i18n("Looking for what can find your files…")
                : i18n("Looking for what can search the web…")
        }
    }

    QQC2.Label {
        visible: !chooser.loading && chooser.choices.length === 0
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        text: i18n("Nothing on this computer can do this yet. Use Connect by hand below if you have a tool for it.")
    }

    Repeater {
        model: chooser.loading ? [] : chooser.choices

        ColumnLayout {
            id: option

            required property var modelData
            readonly property bool busy: chooser.usingId === modelData.id
            readonly property string error: chooser.errors[modelData.id] || ""

            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    level: 4
                    text: option.modelData.title
                }

                QQC2.Label {
                    visible: option.modelData.recommended
                    text: i18n("Recommended")
                    color: Kirigami.Theme.positiveTextColor
                    font: Kirigami.Theme.smallFont
                }

                QQC2.BusyIndicator {
                    visible: option.busy
                    running: option.busy
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }

                QQC2.Button {
                    text: option.busy ? i18n("Setting up…") : i18n("Use this")
                    icon.name: "dialog-ok-apply"
                    highlighted: option.modelData.recommended
                    enabled: option.modelData.ready && chooser.usingId === "" && chooser.filled(option.modelData)
                    onClicked: chooser.use(option.modelData)
                }
            }

            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: option.modelData.detail
            }

            QQC2.Label {
                visible: option.modelData.privacy.length > 0
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: option.modelData.privacy
            }

            Repeater {
                model: option.modelData.inputs

                RowLayout {
                    id: input
                    Layout.fillWidth: true

                    required property var modelData
                    readonly property string key: option.modelData.id + "/" + modelData.name

                    spacing: Kirigami.Units.smallSpacing

                    QQC2.TextField {
                        Layout.fillWidth: true
                        placeholderText: input.modelData.label
                        echoMode: input.modelData.secret ? TextInput.Password : TextInput.Normal
                        text: chooser.typed[input.key] || ""
                        Accessible.name: input.modelData.label
                        onTextEdited: chooser.typed = Object.assign({}, chooser.typed, { [input.key]: text })
                    }

                    QQC2.Button {
                        visible: (input.modelData.help_url || "").length > 0
                        text: input.modelData.secret ? i18n("Get one") : i18n("What is this?")
                        icon.name: "internet-services"
                        onClicked: Qt.openUrlExternally(input.modelData.help_url)
                    }
                }
            }

            QQC2.Label {
                visible: option.busy
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
                text: i18n("Setting it up and trying a search. The first time can take a minute.")
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: option.modelData.problem.length > 0 || option.error.length > 0
                type: option.error.length > 0 ? Kirigami.MessageType.Error : Kirigami.MessageType.Warning
                text: option.error.length > 0 ? option.error : option.modelData.problem
            }
        }
    }
}
