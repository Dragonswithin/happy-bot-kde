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
 * optional drive label (it runs when that drive is plugged in), a pause
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
 * Holds only the reminder list and the add form; routines are saved through
 * `page.save` (DaemonSettings.qml).
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property var routines: (page.settings && page.settings.routines) || ({})
    readonly property var routineNames: Object.keys(routines).sort()
    property var reminders: []

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

    component Hint: QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Routines")
    }

    Hint {
        text: i18n("A routine is a request you can run by typing its name in the bar. It can also run on a schedule or when files appear in a folder; then anything that would need your approval is skipped and the result arrives as a notification.")
    }

    // Repeated rows go inside one column: a Repeater placed directly in a
    // FormLayout can insert its rows after later siblings.
    ColumnLayout {
        Kirigami.FormData.label: i18n("Saved:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            visible: section.routineNames.length === 0
            text: i18n("None yet")
            opacity: 0.7
        }

        Repeater {
            model: section.routineNames

            ColumnLayout {
                id: routine

                required property string modelData
                readonly property var entry: section.routines[modelData] || ({})

                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Label {
                        text: routine.modelData
                        font.bold: true
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 8
                    }

                    QQC2.Switch {
                        text: i18n("Runs on its own")
                        checked: routine.entry.enabled === true
                        onToggled: section.update(routine.modelData, "enabled", checked)
                    }

                    QQC2.Button {
                        text: i18n("Try it")
                        icon.name: "media-playback-start"
                        onClicked: section.tryRoutine(routine.modelData)
                    }

                    QQC2.ToolButton {
                        icon.name: "edit-delete"
                        text: i18n("Delete %1", routine.modelData)
                        display: QQC2.AbstractButton.IconOnly
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                        onClicked: {
                            const name = routine.modelData;
                            section.page.save(function(settings) { delete settings.routines[name]; });
                        }
                    }
                }

                QQC2.TextField {
                    Layout.minimumWidth: Kirigami.Units.gridUnit * 22
                    text: routine.entry.request || ""
                    placeholderText: i18n("What to do")
                    onEditingFinished: section.update(routine.modelData, "request", text.trim())
                }

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.TextField {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 10
                        text: routine.entry.schedule || ""
                        placeholderText: i18n("Schedule, e.g. Mon..Fri 08:30")
                        onEditingFinished: section.update(routine.modelData, "schedule", text.trim())
                    }

                    QQC2.TextField {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 11
                        text: routine.entry.watch_folder || ""
                        placeholderText: i18n("Or watch a folder, e.g. ~/Inbox")
                        onEditingFinished: section.update(routine.modelData, "watch_folder", text.trim())
                    }

                    QQC2.TextField {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 9
                        text: routine.entry.drive_label || ""
                        placeholderText: i18n("Or when this drive is plugged in")
                        onEditingFinished: section.update(routine.modelData, "drive_label", text.trim())
                    }
                }
            }
        }
    }

    QQC2.Label {
        text: i18n("New routine:")
        font.bold: true
    }

    QQC2.TextField {
        id: newName
        Kirigami.FormData.label: i18n("Name:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 14
        placeholderText: i18n("e.g. start work")
    }

    QQC2.TextField {
        id: newRequest
        Kirigami.FormData.label: i18n("Request:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 22
        placeholderText: i18n("e.g. Open Kate and Konsole side by side and turn on Do Not Disturb")
    }

    QQC2.TextField {
        id: newSchedule
        Kirigami.FormData.label: i18n("Schedule:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 14
        placeholderText: i18n("Optional, e.g. daily, Mon..Fri 08:30, *-*-01 09:00")
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

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Reminders")
    }

    ColumnLayout {
        Kirigami.FormData.label: i18n("Set:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        spacing: 0

        QQC2.Label {
            visible: section.reminders.length === 0
            text: i18n("None. Ask the assistant, e.g. \"remind me at 4 to call the vet\".")
            opacity: 0.7
        }

        Repeater {
            model: section.reminders

            RowLayout {
                id: reminderRow

                required property var modelData

                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    text: reminderRow.modelData.when
                    Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                }

                QQC2.Label {
                    text: reminderRow.modelData.text
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 14
                    elide: Text.ElideRight
                }

                QQC2.ToolButton {
                    icon.name: "edit-delete"
                    text: i18n("Cancel this reminder")
                    display: QQC2.AbstractButton.IconOnly
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                    onClicked: section.page.client.request("POST", "/reminders/cancel", { id: reminderRow.modelData.id },
                        function(data) { section.loadReminders(); },
                        function(data) { section.page.report(data.error || i18n("Could not cancel it"), true); })
                }
            }
        }
    }
}
