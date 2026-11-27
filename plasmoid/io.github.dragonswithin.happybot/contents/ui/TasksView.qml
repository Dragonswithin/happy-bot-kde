/* SPDX-License-Identifier: MIT */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

ColumnLayout {
    id: view
    required property AssistantSession session
    required property color accent
    property var tasks: []
    property var draft: null
    property var pendingDelete: null
    property string message: ""
    property bool busy: false
    property string taskSnapshot: ""
    property int revision: 0
    readonly property var priorities: ["none", "low", "normal", "high"]
    readonly property var repeats: ["none", "daily", "weekly", "monthly"]
    readonly property var groups: [...new Set(tasks.map(task => task.group).filter(Boolean))].sort()
    readonly property var parents: tasks.filter(task => !task.parent && task.id !== draft?.id)
    readonly property var rows: {
        const selectedGroup = groupFilter.currentIndex > 0 ? groups[groupFilter.currentIndex - 1] : "";
        const byId = new Map(tasks.map(task => [task.id, task]));
        const ordered = tasks.filter(task => (status.currentIndex === 0 || task.done === (status.currentIndex === 2))
            && (!selectedGroup || (task.group || byId.get(task.parent)?.group) === selectedGroup));
        ordered.sort((a, b) => {
            if (sorting.currentIndex === 1)
                return priorities.indexOf(b.priority) - priorities.indexOf(a.priority) || a.text.localeCompare(b.text);
            return (a.due || "9999").localeCompare(b.due || "9999") || a.text.localeCompare(b.text);
        });
        const visibleIds = new Set(ordered.map(task => task.id));
        const children = new Map();
        for (const task of ordered) {
            if (!children.has(task.parent)) children.set(task.parent, []);
            children.get(task.parent).push(task);
        }
        const result = [];
        for (const task of ordered) {
            if (!visibleIds.has(task.parent)) result.push(task, ...(children.get(task.id) || []));
        }
        return result;
    }

    function applyTasks(items) {
        const snapshot = JSON.stringify(items);
        if (snapshot !== taskSnapshot) {
            taskSnapshot = snapshot;
            tasks = items;
        }
    }

    function refresh() {
        if (busy)
            return;
        const request = ++revision;
        session.request("GET", "/tasks", null, data => {
            if (request !== revision) return;
            applyTasks(data.tasks);
            if (data.warning) message = data.warning;
        }, error => { if (request === revision) message = error.error || i18n("Could not load tasks."); });
    }

    function save(action, payload) {
        if (busy)
            return;
        revision++;
        busy = true;
        message = "";
        session.request("POST", "/tasks", Object.assign({action: action}, payload), data => {
            applyTasks(data.tasks);
            pendingDelete = null;
            draft = null;
            busy = false;
            message = data.warning || "";
            addButton.forceActiveFocus();
        }, error => {
            busy = false;
            message = error.error || i18n("Could not save the task.");
        });
    }

    function edit(task, parent = "") {
        draft = task || { id: "", text: "", group: "", due: "", priority: "none", repeat: "none",
                         parent: parent, reminder: "" };
        titleField.text = draft.text;
        groupField.text = draft.group;
        dueField.text = draft.due;
        reminderField.text = draft.reminder;
        priorityField.currentIndex = Math.max(0, priorities.indexOf(draft.priority));
        repeatField.currentIndex = Math.max(0, repeats.indexOf(draft.repeat));
        parentField.currentIndex = parents.findIndex(task => task.id === draft.parent) + 1;
        titleField.forceActiveFocus();
    }

    function back() {
        if (busy)
            return true;
        if (!draft && !pendingDelete)
            return false;
        draft = null;
        pendingDelete = null;
        addButton.forceActiveFocus();
        return true;
    }

    onVisibleChanged: {
        if (visible) refresh();
        else if (!busy) { draft = null; pendingDelete = null; }
    }

    Timer {
        interval: 2500
        running: view.visible && !view.draft && !view.pendingDelete
        repeat: true
        onTriggered: view.refresh()
    }

    RowLayout {
        Layout.fillWidth: true
        visible: !view.draft
        PlasmaComponents.Button {
            id: addButton
            icon.name: "list-add"
            text: i18n("New task")
            onClicked: view.edit(null)
        }
        AssistantComboBox {
            id: status
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Task status")
            model: [i18n("All tasks"), i18n("Open"), i18n("Completed")]
            currentIndex: 1
        }
        AssistantComboBox {
            id: groupFilter
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Task group")
            model: [i18n("All groups"), ...view.groups]
        }
        AssistantComboBox {
            id: sorting
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Sort tasks")
            model: [i18n("Due date"), i18n("Priority")]
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: view.message.length > 0
        text: view.message
    }

    GridLayout {
        visible: view.draft !== null
        enabled: !view.busy
        Layout.fillWidth: true
        columns: 2

        PlasmaComponents.Label { text: i18n("Task") }
        PlasmaComponents.TextField {
            id: titleField
            objectName: "taskTitle"
            Layout.fillWidth: true
            Accessible.name: i18n("Task")
            onAccepted: saveButton.clicked()
        }
        PlasmaComponents.Label { text: i18n("Group") }
        PlasmaComponents.TextField {
            id: groupField
            Layout.fillWidth: true
            Accessible.name: i18n("Group")
        }
        PlasmaComponents.Label { text: i18n("Priority") }
        AssistantComboBox {
            id: priorityField
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Priority")
            model: [i18n("None"), i18n("Low"), i18n("Normal"), i18n("High")]
        }
        PlasmaComponents.Label { text: i18n("Due date") }
        PlasmaComponents.TextField {
            id: dueField
            Layout.fillWidth: true
            Accessible.name: i18n("Due date")
            placeholderText: i18n("YYYY-MM-DD")
        }
        PlasmaComponents.Label { text: i18n("Repeat") }
        AssistantComboBox {
            id: repeatField
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Repeat")
            model: [i18n("Never"), i18n("Daily"), i18n("Weekly"), i18n("Monthly")]
        }
        PlasmaComponents.Label { text: i18n("Parent task") }
        AssistantComboBox {
            id: parentField
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            accent: view.accent
            nativeLook: !view.session.ui.robot_mascot
            Accessible.name: i18n("Parent task")
            model: [i18n("None"), ...view.parents.map(task => task.text)]
        }
        PlasmaComponents.Label { text: i18n("Remind at") }
        PlasmaComponents.TextField {
            id: reminderField
            Layout.fillWidth: true
            Accessible.name: i18n("Reminder time")
            placeholderText: i18n("HH:MM on the due date")
        }
        RowLayout {
            Layout.columnSpan: 2
            Layout.alignment: Qt.AlignRight
            PlasmaComponents.Button {
                text: i18n("Cancel")
                onClicked: view.back()
            }
            PlasmaComponents.Button {
                id: saveButton
                text: i18n("Save task")
                enabled: titleField.text.trim().length > 0
                onClicked: {
                    if (!enabled || !view.draft) return;
                    view.save(view.draft.id ? "edit" : "create", {
                        id: view.draft.id, text: titleField.text, group: groupField.text, due: dueField.text,
                        priority: view.priorities[priorityField.currentIndex], repeat: view.repeats[repeatField.currentIndex],
                        parent: view.parents[parentField.currentIndex - 1]?.id || "", reminder: reminderField.text
                    });
                }
            }
        }
    }

    PlasmaComponents.Label {
        visible: !view.draft && !view.rows.length
        text: i18n("No tasks match this view.")
        Layout.fillWidth: true
    }

    Repeater {
        model: view.draft ? [] : view.rows
        delegate: ColumnLayout {
            id: row
            required property var modelData
            Layout.fillWidth: true
            Layout.leftMargin: modelData.parent ? Kirigami.Units.largeSpacing : 0
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents.CheckBox {
                    Accessible.name: row.modelData.done ? i18n("Reopen %1", row.modelData.text)
                        : i18n("Complete %1", row.modelData.text)
                    checked: row.modelData.done
                    enabled: !view.busy
                    onClicked: {
                        const action = row.modelData.done ? "reopen" : "complete";
                        checked = Qt.binding(() => row.modelData.done);
                        view.save(action, {id: row.modelData.id});
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        text: row.modelData.text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        font.strikeout: row.modelData.done
                    }
                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        readonly property var task: row.modelData
                        text: [task.group, task.due ? i18n("Due %1", task.due) : "",
                               task.priority !== "none" ? priorityField.model[view.priorities.indexOf(task.priority)] : "",
                               task.repeat !== "none" ? repeatField.model[view.repeats.indexOf(task.repeat)] : "",
                               task.reminder ? i18n("Reminder %1", task.reminder) : ""].filter(Boolean).join(" · ")
                        visible: text.length > 0
                        wrapMode: Text.Wrap
                        font: Kirigami.Theme.smallFont
                    }
                }
                PlasmaComponents.ToolButton {
                    icon.name: "list-add"
                    visible: !row.modelData.parent
                    Accessible.name: i18n("Add subtask to %1", row.modelData.text)
                    enabled: !view.busy
                    onClicked: view.edit(null, row.modelData.id)
                }
                PlasmaComponents.ToolButton {
                    icon.name: "document-edit"
                    Accessible.name: i18n("Edit %1", row.modelData.text)
                    enabled: !view.busy
                    onClicked: view.edit(row.modelData)
                }
                PlasmaComponents.ToolButton {
                    icon.name: "edit-delete"
                    Accessible.name: i18n("Delete %1", row.modelData.text)
                    enabled: !view.busy
                    onClicked: view.pendingDelete = row.modelData
                }
            }
            RowLayout {
                visible: view.pendingDelete?.id === row.modelData.id
                PlasmaComponents.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: i18n("Delete this task and its subtasks?")
                }
                PlasmaComponents.Button { text: i18n("Cancel"); onClicked: view.back() }
                PlasmaComponents.Button {
                    text: i18n("Delete")
                    enabled: !view.busy
                    onClicked: view.save("delete", {id: row.modelData.id})
                }
            }
        }
    }
}
