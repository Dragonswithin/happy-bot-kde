/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import QtCore

import org.kde.kirigami as Kirigami

/**
 * The "History & Folders" page's section (ConfigHistory.qml).
 *
 * Each clear button sends its own kind to POST /history/clear after confirmation.
 * history_days controls how long a conversation is kept after its last use.
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
ColumnLayout {
    id: section
    spacing: Kirigami.Units.largeSpacing

    required property var page

    readonly property var overrides: page.settings ? page.settings.folders : ({})
    readonly property var personal: (page.settings && page.settings.personal) || ({})
    property string confirmingKind: ""
    property string clearingKind: ""
    readonly property var historyKinds: [
        { kind: "search", title: i18n("Search history"),
          detail: i18n("Clear recent web searches, frequent sites, recent items and requests recalled with the arrow keys. Keep your pinned and hidden site choices."),
          done: i18n("Search history cleared.") },
        { kind: "conversations", title: i18n("Saved conversations"),
          detail: i18n("Stop active replies and delete all conversations, including pinned chats."),
          done: i18n("Conversations cleared.") },
        { kind: "activity", title: i18n("Action history"),
          detail: i18n("Clear Happy Bot’s record of actions it ran or declined this session."),
          done: i18n("Action history cleared.") },
        { kind: "undo", title: i18n("Undo history"),
          detail: i18n("Delete undo records and their backup copies. Happy Bot will lose the ability to reverse those changes."),
          done: i18n("Undo history cleared.") },
        { kind: "usage", title: i18n("Past model usage"),
          detail: i18n("Delete token counts and costs from previous months. This month’s totals still count toward your spending limits."),
          done: i18n("Past model usage cleared.") },
        { kind: "cache", title: i18n("Temporary cache"),
          detail: i18n("Remove temporary context screenshots and leftover voice clips, and reset the graphs in System info."),
          done: i18n("Temporary cache cleared.") }
    ]

    property var exportChoices: []
    property bool exportBusy: false
    property var exportChoice: null

    function chooseExport() {
        section.exportBusy = true;
        section.page.client.request("GET", "/conversations", null, data => {
            section.exportBusy = false;
            const chats = data.conversations || [];
            if (!chats.length) {
                section.page.report(i18n("There are no conversations to export."), false);
                return;
            }
            const choices = chats.map(chat => ({
                id: chat.id, title: chat.title || i18n("Untitled conversation"),
                label: (chat.title || i18n("Untitled conversation")) + " · "
                    + new Date(chat.updated * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat)
            }));
            choices.splice(1, 0, { all: true, label: i18n("All conversations (one Markdown file)") });
            section.exportChoices = choices;
        }, data => {
            section.exportBusy = false;
            section.page.report(data.error || i18n("Could not load conversations."), true);
        });
    }

    function saveExport(url) {
        const location = url.toString();
        if (!location.startsWith("file:///")) {
            section.page.report(i18n("Choose a local folder for the Markdown file."), true);
            return;
        }
        const body = section.exportChoice.all ? {all: true} : {id: section.exportChoice.id};
        body.path = decodeURIComponent(location.slice(7));
        section.exportBusy = true;
        section.page.client.request("POST", "/conversations/export", body, () => {
            section.exportBusy = false;
            section.exportChoices = [];
            section.page.report(i18n("Saved to %1", body.path), false);
        }, data => {
            section.exportBusy = false;
            section.page.report(data.error || i18n("Could not save the Markdown file."), true);
        });
    }

    Dialogs.FileDialog {
        id: exportDialog
        objectName: "markdownFileDialog"
        title: i18n("Save conversations as Markdown")
        fileMode: Dialogs.FileDialog.SaveFile
        defaultSuffix: "md"
        nameFilters: [i18n("Markdown files (*.md)")]
        onAccepted: section.saveExport(selectedFile)
    }

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

    function clearHistory(choice) {
        if (section.clearingKind) return;
        if (section.confirmingKind !== choice.kind) {
            section.confirmingKind = choice.kind;
            return;
        }
        section.clearingKind = choice.kind;
        section.page.client.request("POST", "/history/clear", { kind: choice.kind }, () => {
            section.clearingKind = "";
            section.confirmingKind = "";
            if (choice.kind === "conversations") section.exportChoices = [];
            section.page.report(choice.done, false);
        }, data => {
            section.clearingKind = "";
            section.page.report(data.error || i18n("Happy Bot could not clear this history. Try again."), true);
        });
    }

    component FolderField: QQC2.TextField {
        required property string folder

        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
        text: section.overrides[folder] || ""
        placeholderText: section.page.effectiveFolders[folder] || ""
        onEditingFinished: section.setFolder(folder, text)
    }

    component PersonalField: QQC2.TextField {
        required property string key
        required property string fallback

        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
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

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Clear history and cache")
        iconName: "view-history"
        description: i18n("Choose what to clear from Happy Bot. Your browser and Plasma keep their own history.")

        Repeater {
            model: section.historyKinds
            ColumnLayout {
                id: row
                required property var modelData
                required property int index
                readonly property bool confirming: section.confirmingKind === modelData.kind
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Separator { visible: row.index > 0; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true
                    QQC2.Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: row.modelData.title
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    QQC2.Button {
                        objectName: "export-" + row.modelData.kind
                        visible: row.modelData.kind === "conversations" && !row.confirming && !section.exportChoices.length
                        enabled: !section.exportBusy && !section.clearingKind
                        text: i18n("Export…")
                        icon.name: "document-export"
                        onClicked: section.chooseExport()
                    }
                    QQC2.Button {
                        objectName: "cancel-" + row.modelData.kind
                        visible: row.confirming
                        enabled: !section.clearingKind
                        text: i18n("Cancel")
                        onClicked: section.confirmingKind = ""
                    }
                    QQC2.Button {
                        objectName: "clear-" + row.modelData.kind
                        enabled: !section.clearingKind
                        text: section.clearingKind === row.modelData.kind ? i18n("Clearing…")
                            : row.confirming ? i18n("Confirm clear") : i18n("Clear…")
                        Accessible.name: row.confirming ? i18n("Confirm clearing %1", row.modelData.title)
                                                       : i18n("Clear %1", row.modelData.title)
                        onClicked: section.clearHistory(row.modelData)
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: row.modelData.detail
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: row.modelData.kind === "conversations" && section.exportChoices.length > 0
                    enabled: !section.exportBusy
                    QQC2.ComboBox {
                        id: exportPicker
                        objectName: "exportPicker-" + row.modelData.kind
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        textRole: "label"
                        model: row.modelData.kind === "conversations" ? section.exportChoices : []
                        Accessible.name: i18n("Conversations to export")
                    }
                    QQC2.Button {
                        objectName: "saveMarkdown-" + row.modelData.kind
                        enabled: exportPicker.currentIndex >= 0
                        text: i18n("Save as…")
                        onClicked: {
                            section.exportChoice = section.exportChoices[exportPicker.currentIndex];
                            const stem = section.exportChoice.all ? i18n("Happy Bot conversations")
                                : section.exportChoice.title.replace(/[\/\\:*?"<>|%#\x00-\x1f]/g, " ").trim();
                            const documents = StandardPaths.writableLocation(StandardPaths.DocumentsLocation).toString();
                            exportDialog.selectedFile = documents + "/" + encodeURIComponent(Array.from(stem || "Happy Bot").slice(0, 48).join("")) + ".md";
                            exportDialog.open();
                        }
                    }
                    QQC2.Button {
                        text: i18n("Cancel")
                        onClicked: section.exportChoices = []
                    }
                }
            }
        }
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Conversation retention")
        iconName: "chronometer"
        description: i18n("Choose how long to keep a chat after you last use it. Pinned chats stay until you delete them or turn off saving.")

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.SpinBox {
                wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
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
        }
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Standard folders")
        iconName: "folder"
        description: i18n("Choose where Happy Bot looks when you ask for a folder. Leave a field empty to use the system folder shown.")

        Kirigami.FormLayout {
            Layout.fillWidth: true

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
        }
    }

    SettingsSection {
        appearance: section.page.settings?.ui
        Layout.fillWidth: true
        title: i18n("Notes and to-dos")
        iconName: "document-edit"
        description: i18n("Happy Bot writes notes and tasks to these Markdown files. Leave a field empty to use the file shown.")

        Kirigami.FormLayout {
            Layout.fillWidth: true

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
        }
    }
}
