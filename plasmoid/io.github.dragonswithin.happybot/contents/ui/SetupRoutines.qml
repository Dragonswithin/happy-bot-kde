/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support

/**
 * The "Routines & Reminders" page's section (ConfigRoutines.qml).
 *
 * Routines: every entry of the daemon's `routines` setting (its meaning is in
 * src/happy_bot/routines.py), each with its request, an optional
 * schedule (systemd calendar syntax), an optional folder to watch, an
 * optional drive label (it runs when that drive is plugged in), an optional
 * network to run on joining (the battery condition is set by asking the
 * assistant), a pause
 * switch and Delete; a form adds one. Edits are saved when a field is left;
 * the daemon validates the schedule and keeps the routine's timers in step.
 * "Try it" runs the request as a dry run (`happy-bot ask --dry-run
 * --notify`), which only looks things up, and the steps it would take arrive
 * as a desktop notification.
 *
 * Reminders: the reminders and timers that are set (`GET /reminders`), with
 * Cancel (`POST /reminders/cancel`). They are created by asking the
 * assistant; this list is for reviewing and cancelling them.
 *
 * Keeps the reminder list, the open routine editor and the add form. Routines are saved through
 * `page.save` (DaemonSettings.qml).
 */
ColumnLayout {
    id: section
    spacing: Kirigami.Units.largeSpacing

    required property var page

    readonly property var routines: (page.settings && page.settings.routines) || ({})
    readonly property var routineNames: Object.keys(routines).sort()
    property var reminders: []
    property string editingRoutine: ""

    function update(name, key, value) {
        if (section.routines[name] && section.routines[name][key] !== value) {
            section.page.save(function(settings) { settings.routines[name][key] = value; });
        }
    }

    function loadReminders() {
        section.page.client.request("GET", "/reminders", null, function(data) {
            section.reminders = data.reminders || [];
        }, function(data) {
            section.reminders = [];
        });
    }

    function shellQuote(text) {
        return "'" + String(text).replace(/'/g, "'\\''") + "'";
    }

    function tryRoutine(name) {
        runner.connectSource("happy-bot ask --dry-run --notify -- " + shellQuote(section.routines[name].request));
        section.page.report(i18n("Trying %1 as a dry run. The steps it would take will appear as a notification.", name), false);
    }

    Component.onCompleted: loadReminders()

    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => disconnectSource(source)
    }

    component RoutineField: QQC2.TextField {
        required property string routineName
        required property string setting
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
        text: (section.routines[routineName] || {})[setting] || ""
        onEditingFinished: section.update(routineName, setting, text.trim())
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Saved routines")
        iconName: "view-list-details"
        description: section.routineNames.length === 0
            ? i18n("No saved routines yet. Give a request a name below to run it from the search bar.")
            : i18n("Type a routine’s name in the search bar to run it. Choose Try it for a preview of the steps.")

        Repeater {
            model: section.routineNames

            ColumnLayout {
                id: routine

                required property int index
                required property string modelData
                readonly property var entry: section.routines[modelData] || ({})
                readonly property bool editing: section.editingRoutine === modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Separator {
                    visible: routine.index > 0
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.smallSpacing
                    Layout.bottomMargin: Kirigami.Units.smallSpacing
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 0

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: routine.modelData
                            wrapMode: Text.Wrap
                            textFormat: Text.PlainText
                            font.weight: Font.DemiBold
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            visible: !routine.editing
                            text: routine.entry.request || ""
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            font: Kirigami.Theme.smallFont
                            opacity: 0.75
                        }
                    }

                    QQC2.ToolButton {
                        text: i18n("Try it")
                        Accessible.name: i18n("Try %1 as a dry run", routine.modelData)
                        icon.name: "media-playback-start"
                        onClicked: section.tryRoutine(routine.modelData)
                    }

                    QQC2.ToolButton {
                        text: i18n("Edit %1", routine.modelData)
                        icon.name: "document-edit"
                        display: QQC2.AbstractButton.IconOnly
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered || visualFocus
                        checkable: true
                        checked: routine.editing
                        onClicked: section.editingRoutine = routine.editing ? "" : routine.modelData
                    }
                }

                Kirigami.FormLayout {
                    Layout.fillWidth: true
                    visible: routine.editing

                    RoutineField {
                        routineName: routine.modelData
                        Kirigami.FormData.label: i18n("Request:")
                        setting: "request"
                        placeholderText: i18n("What to do")
                    }

                    QQC2.Switch {
                        text: i18n("Run automatically")
                        checked: routine.entry.enabled === true
                        onToggled: section.update(routine.modelData, "enabled", checked)
                    }

                    RoutineField {
                        routineName: routine.modelData
                        Kirigami.FormData.label: i18n("Schedule:")
                        setting: "schedule"
                        placeholderText: i18n("e.g. Mon..Fri 08:30")
                    }

                    RoutineField {
                        routineName: routine.modelData
                        Kirigami.FormData.label: i18n("Watch folder:")
                        setting: "watch_folder"
                        placeholderText: i18n("e.g. ~/Inbox")
                    }

                    RoutineField {
                        routineName: routine.modelData
                        Kirigami.FormData.label: i18n("On joining network:")
                        setting: "on_network"
                        placeholderText: i18n("Network name")
                    }

                    RoutineField {
                        routineName: routine.modelData
                        Kirigami.FormData.label: i18n("On connecting drive:")
                        setting: "drive_label"
                        placeholderText: i18n("Drive label")
                    }

                    QQC2.Button {
                        icon.name: "edit-delete"
                        text: i18n("Delete routine")
                        onClicked: {
                            const name = routine.modelData;
                            section.page.save(function(settings) { delete settings.routines[name]; });
                        }
                    }
                }
            }
        }
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Add a routine")
        iconName: "list-add"
        description: i18n("Add a schedule to run the request automatically. Automatic runs skip actions that need approval and send the result in a notification.")

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.TextField {
                id: newName
                Kirigami.FormData.label: i18n("Name:")
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                placeholderText: i18n("e.g. start work")
            }

            QQC2.TextField {
                id: newRequest
                Kirigami.FormData.label: i18n("Request:")
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                placeholderText: i18n("e.g. Open Kate and Konsole side by side")
            }

            QQC2.TextField {
                id: newSchedule
                Kirigami.FormData.label: i18n("Schedule:")
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                placeholderText: i18n("Optional, e.g. Mon..Fri 08:30")
            }

            QQC2.Button {
                text: i18n("Add routine")
                icon.name: "list-add"
                enabled: newName.text.trim().length > 0 && newRequest.text.trim().length > 0
                    && section.routines[newName.text.trim()] === undefined
                onClicked: {
                    const name = newName.text.trim();
                    const entry = { request: newRequest.text.trim(), schedule: newSchedule.text.trim(), watch_folder: "",
                                    drive_label: "", enabled: true };
                    section.page.save(function(settings) {
                        settings.routines = settings.routines || {};
                        settings.routines[name] = entry;
                    }, function() {
                        newName.text = "";
                        newRequest.text = "";
                        newSchedule.text = "";
                    });
                }
            }
        }
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Reminders")
        iconName: "view-calendar-tasks"
        description: section.reminders.length === 0
            ? i18n("No upcoming reminders. Ask Happy Bot to set one, for example “Remind me at 4 to call the vet”.")
            : ""

        Repeater {
            model: section.reminders

            RowLayout {
                id: reminderRow

                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 0

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: reminderRow.modelData.text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: reminderRow.modelData.when
                        textFormat: Text.PlainText
                        font: Kirigami.Theme.smallFont
                        wrapMode: Text.Wrap
                        opacity: 0.75
                    }
                }

                QQC2.ToolButton {
                    icon.name: "edit-delete"
                    text: i18n("Cancel this reminder")
                    display: QQC2.AbstractButton.IconOnly
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered || visualFocus
                    onClicked: section.page.client.request("POST", "/reminders/cancel", { id: reminderRow.modelData.id },
                        function(data) { section.loadReminders(); },
                        function(data) { section.page.report(data.error || i18n("Could not cancel it"), true); })
                }
            }
        }
    }
}
