/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * "Approvals" and "Folders" section of ConfigSetup.qml.
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
ColumnLayout {
    id: section

    required property var page

    readonly property string policy: page.settings ? page.settings.approval_policy : "danger"
    readonly property var overrides: page.settings ? page.settings.folders : ({})

    spacing: Kirigami.Units.smallSpacing

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

    Kirigami.Heading {
        level: 3
        text: i18n("Approvals")
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        opacity: 0.8
        text: i18n("The assistant pauses and asks before it:")
    }

    QQC2.RadioButton {
        text: i18n("Deletes something or changes the operating system (recommended)")
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

    Kirigami.Heading {
        level: 3
        text: i18n("Folders")
        topPadding: Kirigami.Units.largeSpacing
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        opacity: 0.8
        text: i18n("Where the assistant looks when you say Desktop, Documents or Downloads. Leave a field empty to follow the system's setting.")
    }

    Kirigami.FormLayout {
        Layout.fillWidth: true

        Repeater {
            model: ["Desktop", "Documents", "Downloads"]

            QQC2.TextField {
                required property string modelData

                Kirigami.FormData.label: i18n("%1:", modelData)
                Layout.minimumWidth: Kirigami.Units.gridUnit * 18
                text: section.overrides[modelData] || ""
                placeholderText: section.page.effectiveFolders[modelData] || ""
                onEditingFinished: section.setFolder(modelData, text)
            }
        }
    }
}
