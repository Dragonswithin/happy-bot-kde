/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * "Model details" section of ConfigModels.qml: every stored property of the
 * model chosen in SetupModels.qml (the active one), editable in place.
 *
 * Fields map one to one onto a `models.<name>` entry in
 * src/happy_bot/settings.py: address (`base_url`), model id
 * (`model`), API key (`api_key`), extra request headers (`headers`),
 * context window (`context_window`, in tokens) and whether it accepts
 * images (`vision`). Each change is saved as soon as a field is left, and the
 * daemon validates it; a refused value snaps back with the daemon's message.
 *
 * Below them: the model's prices per million tokens (`input_price`,
 * `output_price`), and three `agent` settings about models: a quicker model
 * every request starts on, handing over to the chosen one when it needs
 * more steps or fails (`quick_model`, src/happy_bot/ask_stream.py), the
 * fallback model on this computer used when the chosen one does not answer
 * (`fallback_model`) and the monthly spending cap (`monthly_spend_cap`),
 * with this month's total from `GET /spend` (src/happy_bot/spend.py).
 *
 * The API key and header values are secrets. The daemon never sends them:
 * a stored key arrives as `null`, shown as "stored", and typing a new one
 * replaces it; "Remove key" stores an empty key. Header values work the same
 * way through PairsEditor.qml.
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property string name: page.settings ? page.settings.active_model : ""
    readonly property var model: (page.settings && name && page.settings.models[name]) || null
    property string spent: ""

    Component.onCompleted: page.client.request("GET", "/spend", null, function(data) {
        section.spent = data.total_cost > 0 ? data.total_cost.toFixed(2) : "";
    }, function(data) {})

    function update(key, value) {
        if (!section.model || section.model[key] === value) {
            return;
        }
        const name = section.name;
        section.page.save(function(settings) { settings.models[name][key] = value; });
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Model details")
        visible: section.model !== null
    }

    QQC2.TextField {
        Kirigami.FormData.label: i18n("Address:")
        visible: section.model !== null
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        text: section.model ? section.model.base_url : ""
        placeholderText: "https://api.example.com/v1"
        onEditingFinished: section.update("base_url", text.trim())
    }

    QQC2.TextField {
        Kirigami.FormData.label: i18n("Model:")
        visible: section.model !== null
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        text: section.model ? section.model.model : ""
        onEditingFinished: section.update("model", text.trim())
    }

    RowLayout {
        Kirigami.FormData.label: i18n("API key:")
        visible: section.model !== null
        spacing: Kirigami.Units.smallSpacing

        Kirigami.PasswordField {
            id: key
            Layout.minimumWidth: Kirigami.Units.gridUnit * 14
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
        Kirigami.FormData.label: i18n("Extra headers:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        visible: section.model !== null
        pairs: section.model ? section.model.headers : ({})
        namePlaceholder: i18n("Header")
        onEdited: changed => {
            const name = section.name;
            section.page.save(function(settings) { settings.models[name].headers = changed; });
        }
    }

    QQC2.SpinBox {
        Kirigami.FormData.label: i18n("Context window:")
        visible: section.model !== null
        Layout.minimumWidth: Kirigami.Units.gridUnit * 9
        editable: true
        from: 1024
        to: 10000000
        stepSize: 1024
        value: section.model ? section.model.context_window : 32768
        textFromValue: (value, locale) => i18n("%1 tokens", Number(value).toLocaleString(locale, "f", 0))
        valueFromText: (text, locale) => parseInt(String(text).replace(/[^0-9]/g, "")) || 1024
        onValueModified: section.update("context_window", value)
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Images:")
        visible: section.model !== null
        text: i18n("This model can look at pictures")
        checked: section.model ? section.model.vision : false
        onToggled: section.update("vision", checked)
    }

    component Price: QQC2.TextField {
        required property string field

        visible: section.model !== null
        Layout.maximumWidth: Kirigami.Units.gridUnit * 6
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        validator: DoubleValidator { bottom: 0; top: 10000; decimals: 4 }
        text: section.model ? String(section.model[field] || 0) : "0"
        onEditingFinished: section.update(field, Number(text) || 0)
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Price per million tokens:")
        visible: section.model !== null
        spacing: Kirigami.Units.smallSpacing

        QQC2.Label { text: i18n("in") }
        Price { field: "input_price" }
        QQC2.Label { text: i18n("out") }
        Price { field: "output_price" }
    }

    QQC2.ComboBox {
        id: quick
        Kirigami.FormData.label: i18n("Start with a quicker model:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
        readonly property var choices: [""].concat(Object.keys((section.page.settings || {}).models || {}).sort().filter(
            name => name !== section.name))
        readonly property string current: (section.page.settings && section.page.settings.agent
                                           && section.page.settings.agent.quick_model) || ""
        model: choices.map(name => name === "" ? i18n("No, always use this one") : name)
        currentIndex: Math.max(0, choices.indexOf(current))
        onActivated: index => {
            const wanted = quick.choices[index];
            section.page.save(function(settings) { settings.agent.quick_model = wanted; });
        }
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Small requests are answered by the quicker model. When a request needs more steps, or the quicker model fails, this one takes over and finishes it.")
    }

    QQC2.ComboBox {
        id: fallback
        Kirigami.FormData.label: i18n("If it does not answer:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
        readonly property var choices: [""].concat(Object.keys((section.page.settings || {}).models || {}).sort().filter(
            name => name !== section.name && /^https?:\/\/(127\.|localhost|\[::1\])/.test(section.page.settings.models[name].base_url)))
        readonly property string current: (section.page.settings && section.page.settings.agent
                                           && section.page.settings.agent.fallback_model) || ""
        model: choices.map(name => name === "" ? i18n("Show an error") : i18n("Use %1 (on this computer)", name))
        currentIndex: Math.max(0, choices.indexOf(current))
        onActivated: index => {
            const wanted = fallback.choices[index];
            section.page.save(function(settings) { settings.agent.fallback_model = wanted; });
        }
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Monthly spending cap:")
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 6
            validator: DoubleValidator { bottom: 0; top: 1000000; decimals: 2 }
            text: section.page.settings && section.page.settings.agent ? String(section.page.settings.agent.monthly_spend_cap || 0) : "0"
            onEditingFinished: {
                const cap = Number(text) || 0;
                section.page.save(function(settings) { settings.agent.monthly_spend_cap = cap; });
            }
        }

        QQC2.Label {
            text: section.spent.length > 0 ? i18n("This month: %1", section.spent) : ""
            opacity: 0.7
        }
    }

    QQC2.Label {
        visible: section.model !== null
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Prices are only for totals and the cap; leave 0 for a model on this computer. 0 means no cap. Only a model on this computer is used automatically when the chosen one does not answer.")
    }

    QQC2.Label {
        visible: section.model !== null
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Extra headers are only needed by some hosted services; their documentation says which. The context window is how much of a conversation the model can read at once; longer conversations are shortened to fit.")
    }
}
