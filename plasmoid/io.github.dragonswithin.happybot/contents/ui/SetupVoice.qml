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
SettingsSection {
    id: section
    title: i18n("Voice input")
    iconName: "audio-input-microphone"
    description: i18n("Click the microphone and speak. Pausing, or clicking it again, sends your words to the AI.")

    appearance: page.settings?.ui
    required property var page
    readonly property var voice: page.settings && page.settings.voice ? page.settings.voice : null
    property bool busy: false
    property string result: ""
    property bool resultIsError: false

    function showResult(text, isError) {
        section.result = text;
        section.resultIsError = isError;
    }

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
        section.showResult(i18n("Looking for a speech-to-text service on this computer…"), false);
        section.page.client.request("POST", "/voice/find", {}, function(data) {
            section.busy = false;
            address.text = data.base_url;
            section.set("base_url", data.base_url);
            section.showResult(i18n("Found a speech service on this computer."), false);
        }, function(data) {
            section.busy = false;
            section.showResult(data.error || i18n("No speech-to-text service answered on this computer."), true);
        });
    }

    function test() {
        section.showResult(i18n("Testing the speech service…"), false);
        section.busy = true;
        section.page.client.request("POST", "/voice/check", { voice: section.typed() }, function(data) {
            section.busy = false;
            section.showResult(i18n("The speech service answers. Click the microphone and talk."), false);
        }, function(data) {
            section.busy = false;
            section.showResult(data.error || i18n("The speech service did not answer."), true);
        });
    }

    QQC2.CheckBox {
        id: micShown
        text: i18n("Show the microphone")
        checked: section.voice ? section.voice.enabled : false
        onToggled: section.set("enabled", checked)
    }

    QQC2.Button {
        id: serviceSettings
        text: i18n("Speech service settings")
        icon.name: checked ? "arrow-down" : "arrow-right"
        checkable: true
    }

    Kirigami.FormLayout {
        visible: serviceSettings.checked
        Layout.fillWidth: true

        QQC2.TextField {
            id: address
            Kirigami.FormData.label: i18n("Service address:")
            Layout.fillWidth: true
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

        QQC2.TextField {
            id: model
            Kirigami.FormData.label: i18n("Speech model:")
            Layout.fillWidth: true
            placeholderText: i18n("Optional, e.g. whisper-v3:turbo")
            text: section.voice ? section.voice.model : ""
            onEditingFinished: section.set("model", text.trim())
        }

        QQC2.TextField {
            id: language
            Kirigami.FormData.label: i18n("Language code:")
            Layout.preferredWidth: Kirigami.Units.gridUnit * 8
            placeholderText: i18n("e.g. en or de")
            text: section.voice ? section.voice.language : "en"
            onEditingFinished: section.set("language", text.trim())
        }

        QQC2.Button {
            text: i18n("Test speech service")
            icon.name: "media-playback-start"
            enabled: !section.busy && address.text.trim().length > 0
            onClicked: section.test()
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: serviceSettings.checked && section.result.length > 0
        type: section.resultIsError ? Kirigami.MessageType.Error : Kirigami.MessageType.Information
        text: section.result
    }

    QQC2.Label {
        visible: serviceSettings.checked
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        text: i18n("Set a key for “Talk to Happy Bot” in System Settings → Shortcuts → Happy Bot Shortcuts.")
    }
}
