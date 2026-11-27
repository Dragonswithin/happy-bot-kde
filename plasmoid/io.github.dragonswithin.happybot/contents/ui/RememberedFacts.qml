/* SPDX-License-Identifier: MIT */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

SettingsSection {
    id: section
    required property var page
    required property bool instructionsSaved
    property var facts: page.settings?.agent?.remembered_facts || []
    property string editing: ""
    property string deleting: ""
    property bool busy: false
    property int revision: 0
    readonly property var legacy: (page.settings?.agent?.instructions || "").split("\n")
        .filter((line, index, lines) => line.startsWith("- ") && lines.indexOf(line) === index
            && lines.lastIndexOf(line) === index)
    readonly property var shown: facts.filter(fact => fact.toLowerCase().includes(search.text.trim().toLowerCase()))
    appearance: page.settings?.ui
    title: i18n("Remembered facts")
    iconName: "document-properties"
    description: i18n("Facts you save here can be shared with the models allowed under Application context.")

    function refresh() {
        if (!visible || busy || !page.settings)
            return;
        const request = ++revision;
        page.client.request("GET", "/memory", null, data => {
            if (revision === request && JSON.stringify(facts) !== JSON.stringify(data.facts))
                facts = data.facts;
        }, () => {});
    }

    function change(action, old, fact) {
        if (busy)
            return;
        revision++;
        busy = true;
        page.client.request("POST", "/memory", { action, old, fact }, data => {
            facts = data.settings.agent.remembered_facts;
            if (action === "move")
                page.settings = data.settings;
            editing = "";
            deleting = "";
            entry.clear();
            busy = false;
            page.report(i18n("Saved."), false);
        }, data => {
            busy = false;
            page.report(data.error || i18n("Could not save the remembered fact."), true);
            refresh();
        });
    }

    onVisibleChanged: refresh()
    Timer {
        running: section.visible
        interval: 3000
        repeat: true
        onTriggered: section.refresh()
    }

    QQC2.TextField {
        id: search
        objectName: "rememberedFactsSearch"
        Layout.fillWidth: true
        Accessible.name: i18n("Search remembered facts")
        placeholderText: i18n("Search remembered facts")
    }

    RowLayout {
        Layout.fillWidth: true
        QQC2.TextField {
            id: entry
            objectName: "rememberedFactEntry"
            Layout.fillWidth: true
            enabled: !section.busy
            Accessible.name: section.editing ? i18n("Edit fact") : i18n("New fact")
            placeholderText: section.editing ? i18n("Edit fact") : i18n("New fact")
            maximumLength: 500
            onAccepted: if (store.enabled) store.clicked()
        }
        QQC2.Button {
            id: store
            text: section.editing ? i18n("Save fact") : i18n("Add fact")
            icon.name: section.editing ? "document-save" : "list-add"
            enabled: entry.text.trim().length > 0 && !section.busy && !!section.page.settings
            onClicked: section.change(section.editing ? "edit" : "add", section.editing, entry.text)
        }
        QQC2.Button {
            visible: section.editing.length > 0
            enabled: !section.busy
            text: i18n("Cancel")
            onClicked: { section.editing = ""; entry.clear(); entry.forceActiveFocus(); }
        }
    }

    QQC2.Label {
        visible: section.shown.length === 0
        text: search.text ? i18n("No matching facts.") : i18n("No facts saved yet.")
        opacity: 0.7
    }

    Repeater {
        model: section.shown
        delegate: ColumnLayout {
            id: row
            required property string modelData
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    text: row.modelData
                }
                QQC2.ToolButton {
                    icon.name: "document-edit"
                    Accessible.name: i18n("Edit %1", row.modelData)
                    enabled: !section.busy
                    onClicked: {
                        section.editing = row.modelData;
                        section.deleting = "";
                        entry.text = row.modelData;
                        entry.forceActiveFocus();
                        entry.selectAll();
                    }
                }
                QQC2.ToolButton {
                    icon.name: "edit-delete"
                    objectName: "deleteRememberedFact"
                    Accessible.name: i18n("Delete %1", row.modelData)
                    enabled: !section.busy
                    onClicked: section.deleting = row.modelData
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: section.deleting === row.modelData
                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: i18n("Delete this remembered fact?")
                }
                QQC2.Button { text: i18n("Cancel"); onClicked: section.deleting = "" }
                QQC2.Button {
                    text: i18n("Delete")
                    objectName: "confirmRememberedFactDelete"
                    enabled: !section.busy
                    onClicked: section.change("delete", row.modelData, "")
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: section.legacy.length > 0
        enabled: section.instructionsSaved && !section.busy
        QQC2.ComboBox {
            id: oldLine
            Layout.fillWidth: true
            currentIndex: -1
            displayText: currentIndex < 0 ? i18n("Choose a fact from Your instructions") : currentText
            Accessible.name: i18n("Fact in Your instructions")
            model: section.legacy
        }
        QQC2.Button {
            text: i18n("Move to facts")
            enabled: oldLine.currentIndex >= 0
            onClicked: section.change("move", oldLine.currentText, "")
        }
    }
}
