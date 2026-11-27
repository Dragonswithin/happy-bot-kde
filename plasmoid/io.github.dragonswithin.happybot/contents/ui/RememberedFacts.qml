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
    property var editing: null
    property var deleting: null
    property bool busy: false
    property int revision: 0
    readonly property var legacy: (page.settings?.agent?.instructions || "").split("\n")
        .filter((line, index, lines) => line.startsWith("- ") && lines.indexOf(line) === index
            && lines.lastIndexOf(line) === index)
    readonly property var suggestions: [
        { key: "name", label: i18n("What should Happy Bot call you?"), shortLabel: i18n("Preferred name") },
        { key: "language", label: i18n("What language should Happy Bot reply in?"), shortLabel: i18n("Preferred language") },
        { key: "units", label: i18n("Which measurement units do you prefer?"), shortLabel: i18n("Measurement units") }
    ]
    readonly property var shown: facts.filter(fact => labelFor(fact).toLowerCase().includes(search.text.trim().toLowerCase()))

    function labelFor(fact) {
        const suggestion = suggestions.find(item => item.key === fact.prompt);
        return suggestion ? i18n("%1: %2", suggestion.shortLabel, fact.text) : fact.text;
    }
    appearance: page.settings?.ui
    title: i18n("Remembered facts")
    iconName: "document-properties"
    description: i18n("Every field is optional. Local-only facts stay with models on this computer. Other facts can be sent to hosted models when Application context allows it.")

    function refresh() {
        if (!visible || busy || !page.settings)
            return;
        const request = ++revision;
        page.client.request("GET", "/memory", null, data => {
            if (revision === request && JSON.stringify(facts) !== JSON.stringify(data.facts))
                facts = data.facts;
        }, () => {});
    }

    function change(action, old, fact, localOnly = true, prompt = "") {
        if (busy)
            return;
        revision++;
        busy = true;
        page.client.request("POST", "/memory", { action, old, fact, local_only: localOnly, prompt }, data => {
            facts = data.settings.agent.remembered_facts;
            if (action === "move")
                page.settings = data.settings;
            editing = null;
            deleting = null;
            entry.clear();
            localCheck.checked = true;
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

    Repeater {
        model: section.suggestions
        delegate: ColumnLayout {
            id: guided
            required property var modelData
            readonly property bool saved: section.facts.some(fact => fact.prompt === modelData.key)
            visible: !saved
            Layout.fillWidth: true

            QQC2.Label {
                text: guided.modelData.label
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                QQC2.TextField {
                    id: answer
                    objectName: "rememberedFact-" + guided.modelData.key
                    Layout.fillWidth: true
                    Accessible.name: guided.modelData.label
                    placeholderText: i18n("Optional")
                    maximumLength: 500
                    onAccepted: if (addAnswer.enabled) addAnswer.clicked()
                }
                QQC2.Button {
                    id: addAnswer
                    text: i18n("Save")
                    Accessible.name: i18n("Save %1", guided.modelData.shortLabel)
                    enabled: answer.text.trim().length > 0 && !section.busy
                    onClicked: section.change("add", "", answer.text, guidedPrivacy.checked, guided.modelData.key)
                }
            }
            QQC2.CheckBox {
                id: guidedPrivacy
                text: i18n("Local only")
                checked: true
            }
            onSavedChanged: if (saved) { answer.clear(); guidedPrivacy.checked = true; }
        }
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
            onClicked: section.change(section.editing ? "edit" : "add", section.editing, entry.text, localCheck.checked)
        }
        QQC2.Button {
            visible: section.editing !== null
            enabled: !section.busy
            text: i18n("Cancel")
            onClicked: { section.editing = null; localCheck.checked = true; entry.clear(); entry.forceActiveFocus(); }
        }
    }

    QQC2.CheckBox {
        id: localCheck
        text: i18n("Local only for this fact")
        checked: true
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
            required property var modelData
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    text: section.labelFor(row.modelData)
                }
                QQC2.ToolButton {
                    icon.name: "document-edit"
                    Accessible.name: i18n("Edit %1", section.labelFor(row.modelData))
                    enabled: !section.busy
                    onClicked: {
                        section.editing = row.modelData;
                        localCheck.checked = row.modelData.local_only;
                        section.deleting = null;
                        entry.text = row.modelData.text;
                        entry.forceActiveFocus();
                        entry.selectAll();
                    }
                }
                QQC2.ToolButton {
                    icon.name: "edit-delete"
                    objectName: "deleteRememberedFact"
                    Accessible.name: i18n("Delete %1", section.labelFor(row.modelData))
                    enabled: !section.busy
                    onClicked: section.deleting = row.modelData
                }
            }
            QQC2.CheckBox {
                text: i18n("Local only")
                Accessible.name: i18n("Local only for %1", section.labelFor(row.modelData))
                checked: row.modelData.local_only
                enabled: !section.busy
                onClicked: {
                    const next = checked;
                    checked = Qt.binding(() => row.modelData.local_only);
                    section.change("edit", row.modelData, row.modelData.text, next);
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: section.deleting?.text === row.modelData.text && section.deleting?.prompt === row.modelData.prompt
                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: i18n("Delete this remembered fact?")
                }
                QQC2.Button { text: i18n("Cancel"); onClicked: section.deleting = null }
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
