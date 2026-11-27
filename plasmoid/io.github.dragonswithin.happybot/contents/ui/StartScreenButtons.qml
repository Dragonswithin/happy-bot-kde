/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The Appearance page's "Start screen" setting (ConfigAppearance.qml): which buttons Happy Bot's
 * start screen shows (AssistantWelcome.qml) and in what order.
 *
 * Every button Happy Bot has (`all`) is listed once: the shown ones first, in their order, then the
 * hidden ones. A tick shows or hides one; the arrows move a shown one up or down. Each change is
 * saved at once as `ui.start_screen`, the shown buttons in order (`page.save`, `POST /ui`,
 * src/happy_bot/ui_settings.py), so the panel widget and the app both follow it. `settingsPage` is the
 * Appearance page, which holds the `ui` settings it read.
 */
ColumnLayout {
    id: list

    required property var settingsPage

    readonly property var shown: list.settingsPage.ui && list.settingsPage.ui.start_screen ? list.settingsPage.ui.start_screen : ["files", "web", "help"]
    readonly property var all: [
        { id: "files", label: i18n("Find a file"), icon: "folder-open-symbolic" },
        { id: "web", label: i18n("Search the web"), icon: "globe" },
        { id: "help", label: i18n("Help with the current app"), icon: "help-contents" },
        { id: "tasks", label: i18n("Tasks"), icon: "view-task" },
        { id: "system", label: i18n("System info"), icon: "speedometer" }
    ]
    // Shown buttons in their order, then the rest.
    readonly property var rows: list.shown.map(id => list.all.find(item => item.id === id)).filter(item => !!item)
        .concat(list.all.filter(item => list.shown.indexOf(item.id) < 0))

    spacing: 0

    function save(buttons) {
        list.settingsPage.save({ start_screen: buttons });
    }

    function toggle(id, on) {
        list.save(on ? list.shown.concat([id]) : list.shown.filter(item => item !== id));
    }

    function move(id, delta) {
        const order = list.shown.slice();
        const from = order.indexOf(id);
        const to = from + delta;
        if (from < 0 || to < 0 || to >= order.length) {
            return;
        }
        order.splice(from, 1);
        order.splice(to, 0, id);
        list.save(order);
    }

    Repeater {
        model: list.rows

        RowLayout {
            id: row

            required property var modelData
            readonly property int position: list.shown.indexOf(modelData.id)

            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: row.modelData.label
                icon.name: row.modelData.icon
                checked: row.position >= 0
                onToggled: list.toggle(row.modelData.id, checked)
            }

            QQC2.ToolButton {
                icon.name: "go-up"
                enabled: row.position > 0
                opacity: row.position >= 0 ? 1 : 0
                Accessible.name: i18n("Move %1 up", row.modelData.label)
                QQC2.ToolTip.text: i18n("Earlier on the start screen")
                QQC2.ToolTip.visible: hovered || visualFocus
                onClicked: list.move(row.modelData.id, -1)
            }

            QQC2.ToolButton {
                icon.name: "go-down"
                enabled: row.position >= 0 && row.position < list.shown.length - 1
                opacity: row.position >= 0 ? 1 : 0
                Accessible.name: i18n("Move %1 down", row.modelData.label)
                QQC2.ToolTip.text: i18n("Later on the start screen")
                QQC2.ToolTip.visible: hovered || visualFocus
                onClicked: list.move(row.modelData.id, 1)
            }
        }
    }
}
