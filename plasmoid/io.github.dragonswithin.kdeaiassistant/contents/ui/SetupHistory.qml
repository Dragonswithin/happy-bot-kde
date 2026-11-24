/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The "History & Folders" page's section (ConfigHistory.qml).
 *
 * History: `history_days`, how long a saved conversation is kept after it
 * was last used (0 keeps nothing on disk), and a button that deletes every
 * saved conversation through `POST /conversations/delete` with
 * `{"all": true}`, after a second confirming click.
 *
 * Folders: where the assistant believes the six standard folders are. Each
 * follows the system's own setting (shown in grey, from
 * `page.effectiveFolders`) unless the user types a different one, which is
 * stored as an override in the daemon's `folders` setting; clearing the field
 * removes the override.
 *
 * Notes and to-dos: where `add_note` and the to-do tools keep their two
 * Markdown files (`personal.notes_file` / `personal.todo_file`); empty means
 * Notes.md and To-do.md in Documents.
 *
 * Holds only the confirmation state; every change goes through `page.save`
 * or the daemon.
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property var overrides: page.settings ? page.settings.folders : ({})
    readonly property var personal: (page.settings && page.settings.personal) || ({})
    property bool confirmingDelete: false

    function setFolder(name, path) {
        const wanted = path.trim();
        if (wanted === (section.overrides[name] || "")) {
            return;
        }
        section.page.save(function(settings) {
            if (wanted.length > 0) {
                settings.folders[name] = wanted;
            } else {
                delete settings.folders[name];
            }
        });
    }

    function deleteAll() {
        section.confirmingDelete = false;
        section.page.client.request("POST", "/conversations/delete", { all: true }, function(data) {
            section.page.report(i18n("All saved conversations were deleted."), false);
        }, function(data) {
            section.page.report(data.error || i18n("The conversations could not be deleted"), true);
        });
    }

    component Hint: QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Conversations")
    }

    QQC2.SpinBox {
        Kirigami.FormData.label: i18n("Keep for:")
        from: 0
        to: 3650
        value: section.page.settings ? section.page.settings.history_days : 30
        textFromValue: (value, locale) => value === 0 ? i18n("Don't keep") : i18np("%1 day", "%1 days", value)
        valueFromText: (text, locale) => parseInt(text) || 0
        onValueModified: {
            const days = value;
            if (section.page.settings && days !== section.page.settings.history_days) {
                section.page.save(function(settings) { settings.history_days = days; });
            }
        }
    }

    Hint {
        text: i18n("Counted from when a conversation was last used. Saved conversations stay on this computer, readable only by you.")
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            visible: !section.confirmingDelete
            text: i18n("Delete all saved conversations…")
            icon.name: "edit-delete"
            onClicked: section.confirmingDelete = true
        }

        QQC2.Button {
            visible: section.confirmingDelete
            text: i18n("Delete them all")
            icon.name: "edit-delete"
            palette.buttonText: Kirigami.Theme.negativeTextColor
            onClicked: section.deleteAll()
        }

        QQC2.Button {
            visible: section.confirmingDelete
            text: i18n("Cancel")
            onClicked: section.confirmingDelete = false
        }
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Folders")
    }

    component FolderField: QQC2.TextField {
        required property string folder

        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        text: section.overrides[folder] || ""
        placeholderText: section.page.effectiveFolders[folder] || ""
        onEditingFinished: section.setFolder(folder, text)
    }

    FolderField {
        Kirigami.FormData.label: i18n("Desktop:")
        folder: "Desktop"
    }

    FolderField {
        Kirigami.FormData.label: i18n("Documents:")
        folder: "Documents"
    }

    FolderField {
        Kirigami.FormData.label: i18n("Downloads:")
        folder: "Downloads"
    }

    FolderField {
        Kirigami.FormData.label: i18n("Pictures:")
        folder: "Pictures"
    }

    FolderField {
        Kirigami.FormData.label: i18n("Music:")
        folder: "Music"
    }

    FolderField {
        Kirigami.FormData.label: i18n("Videos:")
        folder: "Videos"
    }

    Hint {
        text: i18n("Leave a field empty to follow the system's setting, shown in grey. The assistant uses these when you say \"my downloads\" or \"my pictures\".")
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Notes and to-dos")
    }

    component PersonalField: QQC2.TextField {
        required property string key
        required property string fallback

        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        text: section.personal[key] || ""
        placeholderText: (section.page.effectiveFolders["Documents"] || "~/Documents") + "/" + fallback
        onEditingFinished: {
            const wanted = text.trim();
            const name = key;
            if (wanted !== (section.personal[name] || "")) {
                section.page.save(function(settings) {
                    settings.personal = settings.personal || {};
                    settings.personal[name] = wanted;
                });
            }
        }
    }

    PersonalField {
        Kirigami.FormData.label: i18n("Notes file:")
        key: "notes_file"
        fallback: "Notes.md"
    }

    PersonalField {
        Kirigami.FormData.label: i18n("To-do file:")
        key: "todo_file"
        fallback: "To-do.md"
    }

    Hint {
        text: i18n("Plain Markdown files you can also open yourself. \"Note: …\" and \"add to my to-do list …\" go here.")
    }
}
