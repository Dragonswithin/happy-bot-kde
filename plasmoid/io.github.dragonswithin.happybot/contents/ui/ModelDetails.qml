/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * One AI's own settings, opened under its row in the list on the AI Model
 * page (SetupModels.qml) with that row's "Settings" button.
 *
 * Fields map one to one onto the `models.<name>` entry in
 * src/happy_bot/settings.py: address (`base_url`), model id (`model`), API
 * key (`api_key`), extra request headers (`headers`), context window
 * (`context_window`, in tokens), whether it accepts images (`vision`), then
 * how it is used in the list: whether it hands long requests to the next AI
 * (`hand_over_long`, src/happy_bot/ask_stream.py) and, for an AI that costs
 * money, its prices per million tokens (`input_price`, `output_price`) and
 * its monthly limit (`monthly_cap`, src/happy_bot/spend.py) with what it has
 * cost this month (`spent`, from `GET /spend`, given by SetupModels.qml).
 * Each change is saved as soon as a field is left; the daemon validates it,
 * and a refused value snaps back with the daemon's message.
 *
 * The API key and header values are secrets. The daemon never sends them:
 * a stored key arrives as `null`, shown as "stored", and typing a new one
 * replaces it; "Remove key" stores an empty key. Header values work the same
 * way through PairsEditor.qml. This component keeps no state of its own.
 */
Kirigami.FormLayout {
    id: section

    required property var page
    required property string name
    property string spent: ""
    property bool online: false

    readonly property var model: (page.settings && page.settings.models[name]) || null
    readonly property bool priced: model !== null && (model.input_price > 0 || model.output_price > 0)

    function update(key, value) {
        if (!section.model || section.model[key] === value) {
            return;
        }
        const name = section.name;
        section.page.save(function(settings) { settings.models[name][key] = value; });
    }

    QQC2.Label {
        visible: section.online
        Layout.fillWidth: true
        Layout.maximumWidth: Math.min(section.width, Kirigami.Units.gridUnit * 24)
        wrapMode: Text.Wrap
        text: i18n("This AI is online: whatever Happy Bot reads for a request, such as your clipboard or a file, is sent to it.")
    }

    QQC2.TextField {
        Kirigami.FormData.label: i18n("Address:")
        Layout.fillWidth: true
        text: section.model ? section.model.base_url : ""
        placeholderText: "https://api.example.com/v1"
        onEditingFinished: section.update("base_url", text.trim())
    }

    QQC2.TextField {
        Kirigami.FormData.label: i18n("Model:")
        Layout.fillWidth: true
        text: section.model ? section.model.model : ""
        onEditingFinished: section.update("model", text.trim())
    }

    RowLayout {
        Layout.fillWidth: true
        Kirigami.FormData.label: i18n("API key:")
        spacing: Kirigami.Units.smallSpacing

        Kirigami.PasswordField {
            Layout.fillWidth: true
            placeholderText: section.model && section.model.api_key === null
                ? i18n("Stored; type to replace") : i18n("None")
            onEditingFinished: {
                if (text.length > 0) {
                    section.update("api_key", text);
                    text = "";
                }
            }
        }

        QQC2.Button {
            visible: section.model !== null && section.model.api_key === null
            text: i18n("Remove key")
            icon.name: "edit-clear"
            onClicked: section.update("api_key", "")
        }
    }

    PairsEditor {
        Layout.fillWidth: true
        Kirigami.FormData.label: i18n("Extra headers:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        pairs: section.model ? section.model.headers : ({})
        namePlaceholder: i18n("Header")
        onEdited: changed => {
            const name = section.name;
            section.page.save(function(settings) { settings.models[name].headers = changed; });
        }
    }

    QQC2.SpinBox {
        wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
        Kirigami.FormData.label: i18n("Context window:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 9
        editable: true
        from: 0
        to: 10000000
        stepSize: 1024
        value: section.model ? section.model.context_window : 0
        textFromValue: (value, locale) => value > 0 ? i18n("%1 tokens", Number(value).toLocaleString(locale, "f", 0)) : i18n("Unknown")
        valueFromText: (text, locale) => { const tokens = parseInt(String(text).replace(/[^0-9]/g, "")); return tokens > 0 ? Math.max(1024, tokens) : 0; }
        onValueModified: section.update("context_window", value)
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Images:")
        text: i18n("This AI can look at pictures")
        checked: section.model ? section.model.vision : false
        onToggled: section.update("vision", checked)
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Long requests:")
        text: i18n("Hand them to the next AI in the list")
        checked: section.model ? section.model.hand_over_long : false
        onToggled: section.update("hand_over_long", checked)
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Math.min(section.width, Kirigami.Units.gridUnit * 24)
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Useful for a quick AI at the top of the list: it answers small requests, and when one needs more than a few steps the next AI finishes it.")
    }

    component Price: QQC2.TextField {
        required property string field

        Layout.maximumWidth: Kirigami.Units.gridUnit * 6
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        validator: DoubleValidator { bottom: 0; top: 10000; decimals: 4 }
        text: section.model ? String(section.model[field] || 0) : "0"
        onEditingFinished: section.update(field, Number(text) || 0)
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Price per million tokens:")
        visible: section.online
        spacing: Kirigami.Units.smallSpacing

        QQC2.Label { text: i18n("in") }
        Price { field: "input_price" }
        QQC2.Label { text: i18n("out") }
        Price { field: "output_price" }
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Monthly limit:")
        visible: section.online
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 6
            enabled: section.priced
            validator: DoubleValidator { bottom: 0; top: 1000000; decimals: 2 }
            text: section.model ? String(section.model.monthly_cap || 0) : "0"
            onEditingFinished: section.update("monthly_cap", Number(text) || 0)
        }

        QQC2.Label {
            text: section.spent.length > 0 ? i18n("This month: %1", section.spent) : ""
            opacity: 0.7
        }
    }

    QQC2.Label {
        visible: section.online
        Layout.fillWidth: true
        Layout.maximumWidth: Math.min(section.width, Kirigami.Units.gridUnit * 24)
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: section.priced
            ? i18n("Once this AI has cost this much in a month, requests skip it and go to the next AI. 0 means no limit.")
            : i18n("Enter its prices to keep track of what it costs and to set a monthly limit.")
    }
}
