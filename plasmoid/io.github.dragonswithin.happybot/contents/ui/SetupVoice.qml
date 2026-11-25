/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The "Voice" section of the AI Model page (ConfigModels.qml): talking to
 * Happy Bot instead of typing. Its fields map one to one onto the daemon's
 * `voice` settings (src/happy_bot/voice.py): whether the microphone shows
 * (`enabled`; in the panel's search bar, the popup and the floating Happy
 * Bot), the speech-to-text service's address (`base_url`, any server with an
 * OpenAI-style `/audio/transcriptions`), the model name sent with the sound
 * (`model`, optional) and the language spoken (`language`).
 *
 * "Find on this computer" asks the daemon to try the model services on this
 * computer (`POST /voice/find`) and fills in the first that turns speech into
 * text; "Test" sends half a second of silence to the address as typed
 * (`POST /voice/check`). Each field is saved when it is left, through
 * `page.save` (DaemonSettings.qml), which also shows the daemon's message.
 * The "Talk to Happy Bot" shortcut has no key until the user gives it one in
 * System Settings (desktop/happy-bot-shortcuts.desktop). The section keeps
 * only `busy`, while a Find or Test is running.
 */
Kirigami.FormLayout {
    id: section

    required property var page
    readonly property var voice: page.settings && page.settings.voice ? page.settings.voice : null
    property bool busy: false

    function set(key, value) {
        if (section.voice && section.voice[key] !== value) {
            section.page.save(function(settings) { settings.voice[key] = value; });
        }
    }

    function typed() {
        return { enabled: micShown.checked, base_url: address.text.trim(), model: model.text.trim(),
                 language: language.text.trim() };
    }

    function find() {
        section.busy = true;
        section.page.report(i18n("Looking for a speech-to-text service on this computer…"), false);
        section.page.client.request("POST", "/voice/find", {}, function(data) {
            section.busy = false;
            address.text = data.base_url;
            section.set("base_url", data.base_url);
        }, function(data) {
            section.busy = false;
            section.page.report(data.error || i18n("No speech-to-text service answered on this computer."), true);
        });
    }

    function test() {
        section.busy = true;
        section.page.client.request("POST", "/voice/check", { voice: section.typed() }, function(data) {
            section.busy = false;
            section.page.report(i18n("The speech service answers. Click the microphone and talk."), false);
        }, function(data) {
            section.busy = false;
            section.page.report(data.error || i18n("The speech service did not answer."), true);
        });
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Voice")
    }

    QQC2.CheckBox {
        id: micShown
        Kirigami.FormData.label: i18n("Microphone:")
        text: i18n("Show a microphone to talk to Happy Bot")
        checked: section.voice ? section.voice.enabled : false
        onToggled: section.set("enabled", checked)
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Click it, talk, and pause: what you said goes to the AI. Click it again to send at once. For a key, set \"Talk to Happy Bot\" in System Settings > Shortcuts > Happy Bot Shortcuts.")
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Speech to text:")
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            id: address
            Layout.minimumWidth: Kirigami.Units.gridUnit * 14
            placeholderText: "http://127.0.0.1:52625/v1"
            text: section.voice ? section.voice.base_url : ""
            onEditingFinished: section.set("base_url", text.trim())
        }

        QQC2.Button {
            text: i18n("Find on this computer")
            icon.name: "edit-find"
            enabled: !section.busy
            onClicked: section.find()
        }
    }

    QQC2.TextField {
        id: model
        Kirigami.FormData.label: i18n("Model:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 14
        placeholderText: i18n("Optional, e.g. whisper-v3:turbo")
        text: section.voice ? section.voice.model : ""
        onEditingFinished: section.set("model", text.trim())
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Language:")
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            id: language
            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            placeholderText: "en"
            text: section.voice ? section.voice.language : "en"
            onEditingFinished: section.set("language", text.trim())
        }

        QQC2.Label {
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Two letters, such as en or de")
        }
    }

    QQC2.Button {
        text: section.busy ? i18n("Testing…") : i18n("Test")
        icon.name: "media-playback-start"
        enabled: !section.busy && address.text.trim().length > 0
        onClicked: section.test()
    }
}
