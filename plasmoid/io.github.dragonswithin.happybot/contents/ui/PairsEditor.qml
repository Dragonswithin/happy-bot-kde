/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * Edits a set of name = value pairs whose values may be secret: a model's
 * extra request headers (ModelDetails.qml) and a tool server's environment
 * (ToolServerDetails.qml).
 *
 * `pairs` is the object as it arrives from the daemon's redacted settings: a
 * stored value is `null` and is never shown. Each stored row offers a field
 * to type a replacement (left empty, the stored value is kept) and a remove
 * button; a last row adds a new pair. Names of stored rows cannot be edited,
 * because a renamed entry would lose its hidden value; remove it and add it
 * again instead.
 *
 * Nothing is saved here: every change emits `edited(changed)` with the whole
 * new object, stored values still `null` (which the daemon reads as "keep"),
 * and the owner saves it.
 */
ColumnLayout {
    id: editor

    property var pairs: ({})
    property string namePlaceholder: i18n("Name")
    property string valuePlaceholder: i18n("Value")
    readonly property var names: Object.keys(pairs || {}).sort()

    signal edited(var changed)

    spacing: Kirigami.Units.smallSpacing

    function withChange(name, value, remove) {
        const changed = Object.assign({}, editor.pairs || {});
        if (remove) {
            delete changed[name];
        } else {
            changed[name] = value;
        }
        editor.edited(changed);
    }

    Repeater {
        model: editor.names

        RowLayout {
            id: row
            Layout.fillWidth: true

            required property string modelData

            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                Layout.fillWidth: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                text: row.modelData
                elide: Text.ElideMiddle
            }

            Kirigami.PasswordField {
                id: replacement
                Layout.fillWidth: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                placeholderText: editor.pairs[row.modelData] === null ? i18n("Stored; type to replace") : editor.valuePlaceholder
                text: editor.pairs[row.modelData] === null ? "" : (editor.pairs[row.modelData] || "")
                onEditingFinished: {
                    const current = editor.pairs[row.modelData];
                    if (text.length > 0 && text !== current) {
                        editor.withChange(row.modelData, text, false);
                    }
                }
            }

            QQC2.ToolButton {
                icon.name: "list-remove"
                text: i18n("Remove %1", row.modelData)
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: editor.withChange(row.modelData, null, true)
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            id: newName
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            placeholderText: editor.namePlaceholder
        }

        Kirigami.PasswordField {
            id: newValue
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            placeholderText: editor.valuePlaceholder
        }

        QQC2.ToolButton {
            icon.name: "list-add"
            text: i18n("Add")
            display: QQC2.AbstractButton.IconOnly
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
            enabled: newName.text.trim().length > 0 && editor.names.indexOf(newName.text.trim()) === -1
            onClicked: {
                editor.withChange(newName.text.trim(), newValue.text, false);
                newName.text = "";
                newValue.text = "";
            }
        }
    }
}
