/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * "Approvals" and "Folders" section of ConfigSetup.qml, as a
 * Kirigami.FormLayout aligned with the other sections.
 *
 * Approvals chooses the daemon's `approval_policy`: which actions pause for
 * the user. The wording mirrors the definition in docs/ROADMAP.md.
 *
 * Folders shows where the assistant believes Desktop, Documents and
 * Downloads are. Each follows the system's own setting (the placeholder
 * shows the current location) unless the user types a different one here,
 * which is stored as an override in the daemon's `folders` setting. Clearing
 * the field removes the override.
 *
 * Holds no state of its own; every change goes through `page.save`.
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property string policy: page.settings ? page.settings.approval_policy : "danger"
    readonly property var overrides: page.settings ? page.settings.folders : ({})

    function setPolicy(value) {
        if (value !== section.policy) {
            section.page.save(function(settings) { settings.approval_policy = value; });
        }
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

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Approvals")
    }

    QQC2.RadioButton {
        Kirigami.FormData.label: i18n("Ask before it:")
        text: i18n("Deletes something or changes the operating system")
        checked: section.policy === "danger"
        onToggled: if (checked) section.setPolicy("danger")
    }

    QQC2.RadioButton {
        text: i18n("Changes anything at all")
        checked: section.policy === "changes"
        onToggled: if (checked) section.setPolicy("changes")
    }

    QQC2.RadioButton {
        text: i18n("Does anything, including looking things up")
        checked: section.policy === "everything"
        onToggled: if (checked) section.setPolicy("everything")
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("The first choice is recommended: everything else happens at once and is listed in the conversation as it runs.")
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

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Leave a field empty to follow the system's setting, shown in grey.")
    }
}
