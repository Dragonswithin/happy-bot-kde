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
        { key: "name", label: i18n("Preferred name") },
        { key: "language", label: i18n("Reply language"), options: [
            ["Arabic", i18n("Arabic")], ["Chinese (Simplified)", i18n("Chinese (Simplified)")],
            ["Chinese (Traditional)", i18n("Chinese (Traditional)")], ["Dutch", i18n("Dutch")],
            ["English", i18n("English")], ["French", i18n("French")], ["German", i18n("German")],
            ["Hindi", i18n("Hindi")], ["Italian", i18n("Italian")], ["Japanese", i18n("Japanese")],
            ["Korean", i18n("Korean")], ["Polish", i18n("Polish")], ["Portuguese", i18n("Portuguese")],
            ["Russian", i18n("Russian")], ["Spanish", i18n("Spanish")], ["Turkish", i18n("Turkish")],
            ["Ukrainian", i18n("Ukrainian")]
        ] },
        { key: "units", label: i18n("Measurement units"), options: [
            ["Metric", i18n("Metric")], ["US customary", i18n("US customary")], ["Imperial", i18n("Imperial")]
        ] }
    ]
    readonly property var shown: facts.filter(fact => !fact.prompt
        && fact.text.toLowerCase().includes(search.text.trim().toLowerCase()))

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
            readonly property var saved: section.facts.find(fact => fact.prompt === modelData.key) ?? null
            readonly property var options: {
                const choices = modelData.options ?? [];
                return saved && !choices.some(choice => choice[0] === saved.text)
                    ? [...choices, [saved.text, saved.text]] : choices;
            }
            readonly property string value: modelData.options
                ? options[picker.currentIndex - 1]?.[0] ?? "" : answer.text.trim()
            readonly property bool confirming: saved !== null && section.deleting?.prompt === modelData.key
            Layout.fillWidth: true

            function restore() {
                answer.text = saved?.text ?? "";
                picker.currentIndex = options.findIndex(choice => choice[0] === saved?.text) + 1;
                guidedPrivacy.checked = saved?.local_only ?? true;
            }

            Component.onCompleted: restore()
            onSavedChanged: restore()

            GridLayout {
                Layout.fillWidth: true
                columns: width >= Kirigami.Units.gridUnit * 27 ? 5 : 2

                QQC2.Label {
                    text: guided.modelData.label
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                    wrapMode: Text.Wrap
                }

                QQC2.TextField {
                    id: answer
                    objectName: "rememberedFact-" + guided.modelData.key
                    visible: !guided.modelData.options
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 10
                    Accessible.name: guided.modelData.label
                    placeholderText: i18n("Optional")
                    maximumLength: 500
                    onAccepted: if (saveAnswer.enabled) saveAnswer.clicked()
                }

                AssistantComboBox {
                    id: picker
                    objectName: "rememberedFactChoice-" + guided.modelData.key
                    visible: !!guided.modelData.options
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                    nativeLook: !section.appearance?.robot_mascot
                    accent: section.accent
                    Accessible.name: guided.modelData.label
                    model: [i18n("Unspecified"), ...guided.options.map(choice => choice[1])]
                }

                QQC2.CheckBox {
                    id: guidedPrivacy
                    text: i18n("Local only")
                    Accessible.name: i18n("Local only for %1", guided.modelData.label)
                }

                QQC2.Button {
                    id: saveAnswer
                    objectName: "saveRememberedFact-" + guided.modelData.key
                    text: i18n("Save")
                    Accessible.name: i18n("Save %1", guided.modelData.label)
                    enabled: !section.busy && (guided.value !== (guided.saved?.text ?? "")
                        || (!!guided.value && guidedPrivacy.checked !== guided.saved?.local_only))
                    onClicked: {
                        if (!guided.value)
                            section.deleting = guided.saved;
                        else
                            section.change(guided.saved ? "edit" : "add", guided.saved, guided.value,
                                guidedPrivacy.checked, guided.modelData.key);
                    }
                }

                QQC2.ToolButton {
                    icon.name: "edit-delete"
                    Accessible.name: i18n("Clear %1", guided.modelData.label)
                    visible: guided.saved !== null
                    enabled: !section.busy
                    onClicked: section.deleting = guided.saved
                }
            }

            RowLayout {
                visible: guided.confirming
                Layout.fillWidth: true
                QQC2.Label {
                    text: i18n("Clear %1?", guided.modelData.label)
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                QQC2.Button {
                    text: i18n("Cancel")
                    onClicked: { section.deleting = null; guided.restore(); }
                }
                QQC2.Button {
                    text: i18n("Clear")
                    enabled: !section.busy
                    onClicked: section.change("delete", guided.saved, "")
                }
            }
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
                    text: row.modelData.text
                }
                QQC2.ToolButton {
                    icon.name: "document-edit"
                    Accessible.name: i18n("Edit %1", row.modelData.text)
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
                    Accessible.name: i18n("Delete %1", row.modelData.text)
                    enabled: !section.busy
                    onClicked: section.deleting = row.modelData
                }
            }
            QQC2.CheckBox {
                text: i18n("Local only")
                Accessible.name: i18n("Local only for %1", row.modelData.text)
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
