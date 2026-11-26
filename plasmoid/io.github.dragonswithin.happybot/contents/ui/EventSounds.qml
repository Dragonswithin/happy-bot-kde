// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: editor
    required property var choices
    signal edited(string event, var fields)
    signal previewRequested(string event, string theme)

    readonly property var themes: Look.appearanceThemes(i18n("Wand"))
    spacing: Kirigami.Units.largeSpacing
    readonly property var groups: [
        { title: i18n("Assistant"), icon: "audio-volume-high-symbolic", events: [
            { id: "open", label: i18n("Happy Bot opens") },
            { id: "error", label: i18n("An error needs attention") },
            { id: "complete", label: i18n("Long task finished") },
            { id: "attention", label: i18n("Answer or approval needed") }] },
        { title: i18n("Alarms, reminders and jobs"), icon: "chronometer", events: [
            { id: "alarm", label: i18n("Alarm or timer rings") },
            { id: "reminder", label: i18n("Reminder is due") },
            { id: "background", label: i18n("Background job finished") }] },
        { title: i18n("Microphone and mascot"), icon: "audio-input-microphone", events: [
            { id: "mic_ready", label: i18n("Microphone ready") },
            { id: "mic_done", label: i18n("Voice recording finished") },
            { id: "nudge", label: i18n("New mascot nudge") }] }
    ]
    Repeater {
        model: editor.groups
        SettingsSection {
            id: group
            required property var modelData
            required property int index
            title: modelData.title
            iconName: modelData.icon
            description: index === 0 ? i18n("Choose which events play a sound. You can preview any sound theme, even when the event is off.") : ""
            Repeater {
                model: group.modelData.events
                GridLayout {
                    id: row
                    required property var modelData
                    readonly property string eventId: modelData.id
                    readonly property var choice: editor.choices[eventId] ?? ({enabled: false, theme: "pip"})
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    columns: width < Kirigami.Units.gridUnit * 22 ? 2 : 3
                    rowSpacing: 0
                    columnSpacing: Kirigami.Units.smallSpacing
                    QQC2.CheckBox {
                        objectName: "enable-" + row.eventId
                        Layout.fillWidth: true
                        Layout.columnSpan: row.columns === 2 ? 2 : 1
                        text: row.modelData.label
                        checked: row.choice.enabled
                        onToggled: editor.edited(row.eventId, {enabled: checked})
                    }
                    QQC2.ComboBox {
                        id: voice
                        objectName: "theme-" + row.eventId
                        Layout.fillWidth: row.columns === 2
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                        Accessible.name: i18n("Sound for %1", row.modelData.label)
                        model: editor.themes
                        textRole: "name"
                        valueRole: "id"
                        currentIndex: editor.themes.findIndex(theme => theme.id === row.choice.theme)
                        wheelEnabled: false
                        onActivated: index => editor.edited(row.eventId, {theme: valueAt(index)})
                    }
                    QQC2.ToolButton {
                        objectName: "preview-" + row.eventId
                        icon.name: "media-playback-start"
                        display: QQC2.AbstractButton.IconOnly
                        text: i18n("Preview %1 — %2", voice.currentText, row.modelData.label)
                        Accessible.name: text
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered || visualFocus
                        onClicked: editor.previewRequested(row.eventId, row.choice.theme)
                    }
                }
            }
        }
    }
}
