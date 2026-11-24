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
 * service which models it offers (`POST /models/probe`); the suggested ones
 * are listed first, and the box also takes a model id typed by hand, for a
 * service that does not list its models. "Add and test" sends
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
    readonly property var modelChoices: {
        if (!selected) {
            return [];
        }
        const suggested = selected.models.map(item => item.id);
        const listed = offered.filter(id => suggested.indexOf(id) === -1).sort();
        return suggested.concat(listed);
    }

    signal added(string name, string message)

    spacing: Kirigami.Units.largeSpacing

    function choose(id) {
        chooser.selectedId = id;
        chooser.offered = [];
        chooser.error = "";
        keyField.text = "";
    }

    function labelFor(id) {
        const suggested = chooser.selected ? chooser.selected.models.find(item => item.id === id) : null;
        return suggested ? i18n("%1 (%2)", id, suggested.label) : id;
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
            preset: chooser.selectedId, api_key: keyField.text.trim(), model: modelBox.editText.trim(),
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

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                id: modelBox
                Layout.minimumWidth: Kirigami.Units.gridUnit * 16
                editable: true
                model: chooser.modelChoices.map(id => chooser.labelFor(id))
                // The list shows labels ("id (Strong)"); choosing one puts its plain id in the box, which is what is sent.
                onActivated: index => editText = chooser.modelChoices[index]
                onModelChanged: if (chooser.modelChoices.length > 0) editText = chooser.modelChoices[0]
            }

            QQC2.BusyIndicator {
                running: chooser.loadingModels
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("The first one is a good start. You can also type the name of another model.")
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
                enabled: !chooser.adding && keyField.text.trim().length > 0 && modelBox.editText.trim().length > 0
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
