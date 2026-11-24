/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The "Search & Tools" page's section (ConfigTools.qml): which tool does file
 * search and web search, which tool servers are connected, a scan that
 * offers the servers the user already set up for other AI programs, and a
 * form to connect one by hand.
 *
 * Each role row has "Set up" ("Choose another…" once set up), which opens
 * RoleChooser.qml: the choices that can do the job on this computer, best
 * first, each used with one press and a test search. "By hand…" opens
 * RoleEditor.qml to pick the server, tool, query argument and result count
 * instead. Each connected server has a
 * details button that opens ToolServerDetails.qml (running, read-only, start
 * command, environment, allowed tools). "Connect by hand…" opens
 * AddToolServer.qml. Editors are created only when opened, because listing a
 * server's tools starts it.
 *
 * A Kirigami.FormLayout. Tool and server names are shown with underscores as
 * spaces; the stored names are unchanged.
 *
 * A scan (`POST /tools/scan`) starts each discovered server briefly and
 * returns its tools and the roles it looks suited for. Choosing "Use for…"
 * imports the server and assigns that role in one step; "Add" imports it
 * without a role so the model can use its tools. Role suggestions are
 * guesses from the tool's wording and are only ever applied by the user.
 *
 * Durable changes go through `page.save` (DaemonSettings.qml) or `POST
 * /tools/import`; this component holds only the scan results and which
 * editors are open.
 */
Kirigami.FormLayout {
    id: section

    required property var page

    readonly property var servers: page.settings ? page.settings.tool_servers : ({})
    readonly property var serverNames: Object.keys(servers).sort()
    readonly property var roles: page.settings ? page.settings.roles : ({})
    property var found: []
    property bool scanning: false
    property bool scanned: false
    property bool addingByHand: false

    function readable(name) {
        return String(name || "").replace(/_/g, " ");
    }

    function roleLabel(role) {
        return role === "file_search" ? i18n("file search") : i18n("web search");
    }

    function scan() {
        section.scanning = true;
        section.page.client.request("POST", "/tools/scan", {}, function(data) {
            section.scanning = false;
            section.scanned = true;
            section.found = data.servers || [];
        }, function(data) {
            section.scanning = false;
            section.page.report(data.error || i18n("Could not look for tools"), true);
        });
    }

    /** Imports a discovered server, then optionally assigns one of its tools to a role. */
    function adopt(server, proposal) {
        section.page.client.request("POST", "/tools/import", {
            name: server.name, source_path: server.source_path, read_only: false
        }, function(data) {
            section.found = section.found.filter(item => item.name !== server.name);
            section.page.settings = data.settings;
            if (proposal) {
                section.page.save(function(settings) { settings.roles[proposal.role] = proposal.config; });
            } else {
                section.page.report(i18n("Added %1.", section.readable(server.name)), false);
            }
        }, function(data) {
            section.page.report(data.error || i18n("Could not add %1", server.name), true);
        });
    }

    component RoleRow: ColumnLayout {
        id: roleRow

        required property string role
        readonly property var config: section.roles[role]
        property bool editing: false
        property bool choosing: false

        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: roleRow.role === "file_search" ? "folder-documents-symbolic" : "globe"
                opacity: roleRow.config ? 1 : 0.5
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            QQC2.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 9
                text: roleRow.config ? section.readable(roleRow.config.tool) : i18n("Not set up")
                opacity: roleRow.config ? 1 : 0.7
            }

            QQC2.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 5
                text: roleRow.config ? i18n("from %1", section.readable(roleRow.config.server)) : ""
                font: Kirigami.Theme.smallFont
                opacity: 0.6
            }

            QQC2.ToolButton {
                visible: roleRow.config !== undefined
                icon.name: "window-close"
                text: i18n("Stop using this for %1", section.roleLabel(roleRow.role))
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: section.page.save(function(settings) { delete settings.roles[roleRow.role]; })
            }

            QQC2.Button {
                text: roleRow.config ? i18n("Choose another…") : i18n("Set up")
                icon.name: roleRow.config ? "" : "dialog-ok-apply"
                highlighted: !roleRow.config
                checkable: true
                checked: roleRow.choosing
                onToggled: {
                    roleRow.choosing = checked;
                    if (checked) {
                        roleRow.editing = false;
                    }
                }
            }

            QQC2.ToolButton {
                text: i18n("By hand…")
                checkable: true
                checked: roleRow.editing
                onToggled: {
                    roleRow.editing = checked;
                    if (checked) {
                        roleRow.choosing = false;
                    }
                }
            }
        }

        Loader {
            active: roleRow.choosing
            visible: active
            Layout.leftMargin: Kirigami.Units.gridUnit

            sourceComponent: RoleChooser {
                page: section.page
                role: roleRow.role
                onDone: roleRow.choosing = false
            }
        }

        Loader {
            active: roleRow.editing
            visible: active
            Layout.leftMargin: Kirigami.Units.gridUnit

            sourceComponent: RoleEditor {
                page: section.page
                role: roleRow.role
                config: roleRow.config
                onSaved: roleRow.editing = false
            }
        }
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Search")
    }

    RoleRow {
        Kirigami.FormData.label: i18n("Files:")
        role: "file_search"
    }

    RoleRow {
        Kirigami.FormData.label: i18n("Web:")
        role: "web_search"
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("File search shows matching files while you type. Web search lets the assistant answer with current information.")
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Tools")
    }

    // Repeated rows go inside one column: a Repeater placed directly in a
    // FormLayout can insert its rows after later siblings.
    ColumnLayout {
        Kirigami.FormData.label: i18n("Connected:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        spacing: 0

        QQC2.Label {
            visible: section.serverNames.length === 0
            text: i18n("None yet")
            opacity: 0.7
        }

        Repeater {
            model: section.serverNames

            ColumnLayout {
                id: connected

                required property string modelData
                readonly property var entry: section.servers[modelData]
                property bool open: false

                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: "plugins"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    }

                    QQC2.Label {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 9
                        text: section.readable(connected.modelData)
                        opacity: connected.entry !== undefined && !connected.entry.enabled ? 0.5 : 1
                    }

                    QQC2.Label {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 5
                        text: connected.entry === undefined ? ""
                            : !connected.entry.enabled ? i18n("switched off")
                            : connected.entry.read_only ? i18n("look-up only") : ""
                        font: Kirigami.Theme.smallFont
                        opacity: 0.6
                    }

                    QQC2.ToolButton {
                        icon.name: "configure"
                        text: i18n("Settings for %1", section.readable(connected.modelData))
                        display: QQC2.AbstractButton.IconOnly
                        checkable: true
                        checked: connected.open
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                        onToggled: connected.open = checked
                    }

                    QQC2.ToolButton {
                        icon.name: "window-close"
                        text: i18n("Disconnect %1", section.readable(connected.modelData))
                        display: QQC2.AbstractButton.IconOnly
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                        onClicked: {
                            const name = connected.modelData;
                            section.page.save(function(settings) {
                                delete settings.tool_servers[name];
                                for (const role of Object.keys(settings.roles)) {
                                    if (settings.roles[role].server === name) {
                                        delete settings.roles[role];
                                    }
                                }
                            });
                        }
                    }
                }

                Loader {
                    active: connected.open && connected.entry !== undefined
                    visible: active
                    Layout.leftMargin: Kirigami.Units.gridUnit
                    Layout.bottomMargin: Kirigami.Units.largeSpacing

                    sourceComponent: ToolServerDetails {
                        page: section.page
                        name: connected.modelData
                        entry: connected.entry
                    }
                }
            }
        }
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            text: i18n("Find installed tools…")
            icon.name: "edit-find"
            enabled: !section.scanning
            onClicked: section.scan()
        }

        QQC2.Button {
            text: i18n("Connect by hand…")
            icon.name: "list-add"
            checkable: true
            checked: section.addingByHand
            onToggled: section.addingByHand = checked
        }

        QQC2.BusyIndicator {
            running: section.scanning
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        visible: section.scanned && section.found.length === 0
        wrapMode: Text.Wrap
        opacity: 0.8
        text: i18n("Nothing more was found. Tools set up for other AI programs on this computer appear here.")
    }

    ColumnLayout {
        visible: section.found.length > 0
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: section.found

            ColumnLayout {
                id: candidate

                required property var modelData

                spacing: 0

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: candidate.modelData.error.length > 0 ? "emblem-warning" : "plugins"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    }

                    QQC2.Label {
                        text: section.readable(candidate.modelData.name)
                    }

                    QQC2.Label {
                        text: candidate.modelData.error.length > 0
                            ? i18n("from %1, could not start", candidate.modelData.source)
                            : i18np("from %2, %1 tool", "from %2, %1 tools", candidate.modelData.tools.length,
                                    candidate.modelData.source)
                        font: Kirigami.Theme.smallFont
                        opacity: 0.6
                    }

                    Repeater {
                        model: candidate.modelData.proposals

                        QQC2.Button {
                            required property var modelData
                            text: i18n("Use for %1", section.roleLabel(modelData.role))
                            QQC2.ToolTip.text: i18n("Use its %1 tool", section.readable(modelData.config.tool))
                            QQC2.ToolTip.visible: hovered
                            onClicked: section.adopt(candidate.modelData, modelData)
                        }
                    }

                    QQC2.Button {
                        text: i18n("Add")
                        icon.name: "list-add"
                        enabled: candidate.modelData.error.length === 0
                        onClicked: section.adopt(candidate.modelData, null)
                    }
                }

                QQC2.Label {
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 24
                    visible: candidate.modelData.error.length > 0
                    text: candidate.modelData.error
                    wrapMode: Text.Wrap
                    font: Kirigami.Theme.smallFont
                    color: Kirigami.Theme.negativeTextColor
                }
            }
        }
    }

    Loader {
        active: section.addingByHand
        visible: active

        sourceComponent: AddToolServer {
            page: section.page
            onAdded: name => {
                section.addingByHand = false;
                section.page.report(i18n("Connected %1. Open its settings to add API keys or choose its tools.", section.readable(name)), false);
            }
        }
    }
}
