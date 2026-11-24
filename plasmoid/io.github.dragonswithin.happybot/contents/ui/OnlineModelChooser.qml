/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * Adding an online AI service in three numbered steps, shown under "Online
 * service…" in SetupModels.qml: pick the service, get and paste an API key,
 * pick a model.
 *
 * The services come from the daemon (`GET /models/presets`,
 * src/happy_bot/model_presets.py): each with a plain description, where the
 * user's words go, the page where its keys are made, short directions, and
 * suggested models (a strong one and a fast one). Pasting a key asks the
 * service which models it offers (`POST /models/probe`). Step 3 shows the
 * service's suggested models as plain choices, the first picked; "Another
 * model…" opens a search field over the service's own list, kept short
 * (eight rows that scroll) and without models that cannot chat (speech,
 * transcription, pictures, embeddings), and takes a model name typed by
 * hand for a service that does not list its models. "Add and test" sends
 * `POST /models/use` (src/happy_bot/model_setup.py), which adds the model,
 * makes it the one asked first when "Ask this one first" is ticked, and
 * tests it; on success `added(name, message)` is emitted, on failure the
 * reason is shown here and nothing changed.
 *
 * Only transient state lives here. The key is sent to the daemon once and
 * never read back.
 */
ColumnLayout {
    id: chooser

    required property var page

    property var presets: []
    property string selectedId: ""
    readonly property var selected: presets.find(item => item.id === selectedId) || null
    property var offered: []
    property bool loadingModels: false
    property bool adding: false
    property string error: ""
    // The model that will be added: a suggested one, or with "Another model" one from the list or typed.
    property string chosenId: ""
    property bool otherModel: false
    property string search: ""
    // Services list every model they have, including ones that cannot chat (speech, transcription,
    // pictures, embeddings); those are left out of "Another model".
    readonly property var chatModels: {
        const notChat = /(tts|transcri|whisper|embed|image|dall-e|audio|realtime|moderation|speech|diariz|vision-preview|search-preview|computer-use|codex-mini)/i;
        const suggested = selected ? selected.models.map(item => item.id) : [];
        return offered.filter(id => !notChat.test(id) && suggested.indexOf(id) === -1).sort();
    }
    readonly property var shownModels: {
        const words = search.trim().toLowerCase();
        return words.length === 0 ? chatModels : chatModels.filter(id => id.toLowerCase().indexOf(words) !== -1);
    }

    signal added(string name, string message)

    spacing: Kirigami.Units.largeSpacing

    function choose(id) {
        chooser.selectedId = id;
        chooser.offered = [];
        chooser.error = "";
        chooser.otherModel = false;
        chooser.search = "";
        keyField.text = "";
        const preset = chooser.presets.find(item => item.id === id);
        chooser.chosenId = preset && preset.models.length > 0 ? preset.models[0].id : "";
    }

    function loadModels() {
        if (!chooser.selected || keyField.text.trim().length === 0) {
            return;
        }
        chooser.loadingModels = true;
        chooser.page.client.request("POST", "/models/probe",
            { base_url: chooser.selected.base_url, api_key: keyField.text.trim() }, function(data) {
                chooser.loadingModels = false;
                chooser.error = "";
                chooser.offered = (data.models || []).map(item => item.id);
            }, function(data) {
                chooser.loadingModels = false;
                chooser.offered = [];
                // A service that does not list models still works with a suggested or typed id;
                // a refused key is worth saying at once.
                if (data.code === "unreachable" && /401|403|key|auth/i.test(data.error || "")) {
                    chooser.error = i18n("%1 did not accept this key. Check that it was copied whole.", chooser.selected.title);
                }
            });
    }

    function add() {
        chooser.adding = true;
        chooser.error = "";
        chooser.page.client.request("POST", "/models/use", {
            preset: chooser.selectedId, api_key: keyField.text.trim(), model: chooser.chosenId.trim(),
            job: askFirst.checked ? "main" : "none"
        }, function(data) {
            chooser.adding = false;
            chooser.page.settings = data.settings;
            keyField.text = "";
            chooser.added(data.name, data.message);
        }, function(data) {
            chooser.adding = false;
            chooser.error = data.error || i18n("That did not work");
        });
    }

    Component.onCompleted: {
        chooser.page.client.request("GET", "/models/presets", null, data => chooser.presets = data.presets || [],
                                    data => chooser.error = data.error || i18n("Could not load the list of services"));
    }

    QQC2.Label {
        text: i18n("1. Which service do you use?")
        font.weight: Font.Bold
    }

    Flow {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: chooser.presets

            QQC2.Button {
                required property var modelData
                text: modelData.title
                checkable: true
                checked: chooser.selectedId === modelData.id
                onClicked: chooser.choose(modelData.id)
            }
        }
    }

    ColumnLayout {
        visible: chooser.selected !== null
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: chooser.selected ? chooser.selected.description : ""
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: chooser.selected ? chooser.selected.privacy : ""
        }

        QQC2.Label {
            Layout.topMargin: Kirigami.Units.largeSpacing
            text: i18n("2. Get your API key and paste it here")
            font.weight: Font.Bold
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: chooser.selected ? chooser.selected.key_steps : ""
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                text: chooser.selected ? i18n("Open the %1 key page", chooser.selected.title) : ""
                icon.name: "internet-services"
                onClicked: Qt.openUrlExternally(chooser.selected.key_url)
            }
        }

        Kirigami.PasswordField {
            id: keyField
            Layout.fillWidth: true
            placeholderText: i18n("Paste the key here")
            onEditingFinished: chooser.loadModels()
        }

        QQC2.Label {
            Layout.topMargin: Kirigami.Units.largeSpacing
            text: i18n("3. Pick a model")
            font.weight: Font.Bold
        }

        // The service's suggested models, each one choice; the first is a good start.
        Repeater {
            model: chooser.selected ? chooser.selected.models : []

            QQC2.RadioButton {
                required property var modelData
                text: i18n("%1 (%2)", modelData.id, modelData.label)
                checked: !chooser.otherModel && chooser.chosenId === modelData.id
                onToggled: if (checked) {
                    chooser.otherModel = false;
                    chooser.chosenId = modelData.id;
                }
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.RadioButton {
                text: i18n("Another model…")
                checked: chooser.otherModel
                onToggled: if (checked) {
                    chooser.otherModel = true;
                    chooser.chosenId = otherField.text.trim();
                }
            }

            QQC2.BusyIndicator {
                running: chooser.loadingModels
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
        }

        ColumnLayout {
            visible: chooser.otherModel
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit
            spacing: Kirigami.Units.smallSpacing

            Kirigami.SearchField {
                id: otherField
                Layout.fillWidth: true
                placeholderText: i18n("Search, or type the model's exact name")
                onTextChanged: {
                    chooser.search = text;
                    chooser.chosenId = text.trim();
                }
            }

            QQC2.Label {
                visible: chooser.offered.length === 0
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: i18n("Paste your key above to see the models this service offers, or type a model's name.")
            }

            // A short list that scrolls, so a service with hundreds of models stays readable.
            QQC2.ScrollView {
                visible: chooser.shownModels.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(chooser.shownModels.length, 8) * Kirigami.Units.gridUnit * 2
                clip: true

                ListView {
                    model: chooser.shownModels
                    delegate: QQC2.ItemDelegate {
                        required property string modelData
                        width: ListView.view.width
                        height: Kirigami.Units.gridUnit * 2
                        text: modelData
                        highlighted: chooser.chosenId === modelData
                        onClicked: {
                            otherField.text = modelData;
                            chooser.chosenId = modelData;
                        }
                    }
                }
            }

            QQC2.Label {
                visible: chooser.offered.length > 0
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: i18np("%1 model that can chat", "%1 models that can chat", chooser.chatModels.length)
            }
        }

        QQC2.CheckBox {
            id: askFirst
            Layout.topMargin: Kirigami.Units.largeSpacing
            text: i18n("Ask this one first")
            checked: true
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                text: chooser.adding ? i18n("Adding and testing…") : i18n("Add and test")
                icon.name: "dialog-ok-apply"
                highlighted: true
                enabled: !chooser.adding && keyField.text.trim().length > 0 && chooser.chosenId.trim().length > 0
                onClicked: chooser.add()
            }

            QQC2.BusyIndicator {
                running: chooser.adding
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        visible: chooser.error.length > 0
        type: Kirigami.MessageType.Error
        text: chooser.error
    }
}
