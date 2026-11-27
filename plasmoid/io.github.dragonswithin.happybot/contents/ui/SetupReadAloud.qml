/* SPDX-License-Identifier: MIT */
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtCore as QtCore
import QtQuick.Dialogs as Dialogs
import org.kde.kirigami as Kirigami

SettingsSection {
    id: section
    required property var page
    readonly property bool nativeLook: !(appearance?.robot_mascot ?? true)
    readonly property var voice: page.settings?.voice || ({})
    property var voices: []
    property var localVoices: []
    readonly property bool usingPiper: voice.speech_engine === "piper"
    onUsingPiperChanged: if (usingPiper) refreshInstalled()
    property var downloads: []
    property bool working: false
    property string failure: ""
    title: i18n("Read aloud")
    iconName: "audio-speakers-symbolic"
    appearance: page.settings?.ui

    function save(key, value) {
        page.save(settings => { settings.voice[key] = value })
    }
    function refreshInstalled() {
        page.client.request("GET", "/speech/voices?engine=piper", null, data => {
            localVoices = data.voices
        }, data => { failure = data.error })
    }
    function fetchVoices(body) {
        working = true
        failure = ""
        page.client.request("POST", "/speech/piper-voices", body, data => {
            working = false
            if (data.path) {
                save("piper_model", data.path)
                refreshInstalled()
            } else downloads = data.voices
        }, data => {
            working = false
            failure = data.error
        })
    }
    Kirigami.FormLayout {
        Layout.fillWidth: true
        AssistantComboBox {
            Kirigami.FormData.label: i18n("Speech engine")
            nativeLook: section.nativeLook
            accent: section.accent
            Accessible.name: i18n("Speech engine")
            model: [i18n("Speech Dispatcher"), i18n("Piper")]
            currentIndex: section.voice.speech_engine === "piper" ? 1 : 0
            onActivated: index => section.save("speech_engine", index ? "piper" : "dispatcher")
        }
        AssistantComboBox {
            visible: section.voice.speech_engine !== "piper"
            Kirigami.FormData.label: i18n("Voice")
            nativeLook: section.nativeLook
            accent: section.accent
            Accessible.name: i18n("Speech Dispatcher voice")
            model: [i18n("System default")].concat(section.voices)
            displayText: section.voice.dispatcher_voice || i18n("System default")
            currentIndex: section.voices.indexOf(section.voice.dispatcher_voice) + 1
            onPressedChanged: if (pressed) {
                section.page.client.request("GET", "/speech/voices", null, data => {
                    section.voices = data.voices
                    section.failure = ""
                }, data => { section.failure = data.error })
            }
            onActivated: index => section.save("dispatcher_voice", index ? section.voices[index - 1] : "")
        }
        AssistantComboBox {
            visible: section.usingPiper && section.localVoices.length > 0
            Kirigami.FormData.label: i18n("Installed voices")
            Accessible.name: i18n("Installed Piper voices")
            accent: section.accent
            nativeLook: section.nativeLook
            model: section.localVoices.map(path => path.split("/").pop().replace(/\.onnx$/, ""))
            currentIndex: section.localVoices.indexOf(section.voice.piper_model)
            displayText: currentIndex < 0 ? i18n("Choose a voice…") : currentText
            onActivated: index => section.save("piper_model", section.localVoices[index])
        }
        QQC2.Button {
            visible: section.voice.speech_engine === "piper"
            Kirigami.FormData.label: i18n("Piper voice")
            text: section.voice.piper_model?.split("/").pop() || i18n("Choose voice file…")
            onClicked: picker.open()
        }
        QQC2.Button {
            visible: section.voice.speech_engine === "piper"
            text: i18n("Browse downloadable voices…")
            enabled: !section.working
            onClicked: section.fetchVoices({})
        }
        AssistantComboBox {
            id: downloadPicker
            nativeLook: section.nativeLook
            accent: section.accent
            visible: section.voice.speech_engine === "piper" && count > 0
            model: section.downloads
            Kirigami.FormData.label: i18n("Available voices")
            Accessible.name: i18n("Available Piper voices")
        }
        QQC2.Button {
            visible: downloadPicker.visible
            enabled: !section.working && !!downloadPicker.currentText
            text: section.working ? i18n("Downloading…") : i18n("Download and use voice")
            onClicked: section.fetchVoices({voice: downloadPicker.currentText})
        }
        ReadAloudButton {
            client: section.page.client
            passage: i18n("Hello from Happy Bot. This is your reading voice.")
            label: i18n("Preview voice")
        }
        QQC2.Label { visible: !!section.failure; text: section.failure }
    }
    Dialogs.FileDialog {
        id: picker
        currentFolder: QtCore.StandardPaths.writableLocation(QtCore.StandardPaths.GenericDataLocation) + "/happy-bot/voices"
        title: i18n("Choose a Piper voice")
        nameFilters: [i18n("Piper voices (*.onnx)")]
        onAccepted: section.save("piper_model", decodeURIComponent(String(selectedFile).replace(/^file:\/\//, "")))
    }
}
