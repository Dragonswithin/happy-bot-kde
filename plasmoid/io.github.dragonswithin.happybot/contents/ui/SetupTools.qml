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
 * server's tools starts it. The "Wikipedia:" row is WikipediaSetup.qml:
 * offline Wikipedia, found on this computer or downloaded, and kept up to date.
 *
 * Browser results are opt-in. Like the panel widget, this page changes those two
 * UI settings through POST /ui so each switch changes just that preference.
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
ColumnLayout {
    id: section
    spacing: Kirigami.Units.largeSpacing

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
        section.addingByHand = false;
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

    function changeBrowserResults(key, enabled) {
        section.page.client.request("POST", "/ui", { changes: { [key]: enabled } }, function(data) {
            section.page.settings = Object.assign({}, section.page.settings, { ui: data.ui });
        }, function(data) {
            section.page.report(data.error || i18n("That search setting could not be saved."), true);
            section.page.reload();
        });
    }

    component RoleRow: ColumnLayout {
        id: roleRow

        required property string role
        readonly property var config: section.roles[role]
        property bool editing: false
        property bool choosing: false

        spacing: Kirigami.Units.smallSpacing

        GridLayout {
            Layout.fillWidth: true
            columns: roleRow.width < Kirigami.Units.gridUnit * 24 ? 1 : 2
            columnSpacing: Kirigami.Units.largeSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    source: roleRow.role === "file_search" ? "folder-documents-symbolic" : "globe"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    Accessible.ignored: true
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    QQC2.Label {
                        text: roleRow.role === "file_search" ? i18n("File search") : i18n("Web search")
                        font.weight: Font.DemiBold
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: roleRow.config
                            ? i18n("%1 from %2", section.readable(roleRow.config.tool), section.readable(roleRow.config.server))
                            : i18n("Not set up")
                        font: Kirigami.Theme.smallFont
                    }
                }
            }

            RowLayout {
                spacing: Kirigami.Units.smallSpacing

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

                QQC2.ToolButton {
                    visible: roleRow.config !== undefined
                    icon.name: "window-close"
                    text: i18n("Stop using this for %1", section.roleLabel(roleRow.role))
                    display: QQC2.AbstractButton.IconOnly
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                    onClicked: section.page.save(function(settings) { delete settings.roles[roleRow.role]; })
                }
            }
        }

        Loader {
            active: roleRow.choosing
            visible: active
            Layout.fillWidth: true

            sourceComponent: RoleChooser {
                page: section.page
                role: roleRow.role
                onDone: roleRow.choosing = false
            }
        }

        Loader {
            active: roleRow.editing
            visible: active
            Layout.fillWidth: true

            sourceComponent: RoleEditor {
                page: section.page
                role: roleRow.role
                config: roleRow.config
                onSaved: roleRow.editing = false
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Search sources")
        iconName: "edit-find"
        description: i18n("Choose the tools that find files as you type and search the web for answers.")

        RoleRow {
            Layout.fillWidth: true
            role: "file_search"
        }

        Kirigami.Separator { Layout.fillWidth: true }

        RoleRow {
            Layout.fillWidth: true
            role: "web_search"
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Browser results")
        iconName: "bookmarks"
        description: i18n("Choose which browser results appear in Happy Bot. Recently visited websites also supply the Frequent sites section in Search the web.")

        QQC2.CheckBox {
            text: i18n("Bookmarks")
            checked: section.page.settings?.ui?.search_bookmarks === true
            onToggled: section.changeBrowserResults("search_bookmarks", checked)
        }

        QQC2.CheckBox {
            text: i18n("Recently visited websites")
            checked: section.page.settings?.ui?.search_history === true
            onToggled: section.changeBrowserResults("search_history", checked)
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: hiddenSites.count > 0
            QQC2.Label { text: i18n("Sites hidden from Frequent sites") }
            RowLayout {
                Layout.fillWidth: true
                QQC2.ComboBox {
                    id: hiddenSites
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    model: section.page.settings?.ui?.web_hidden ?? []
                    Accessible.name: i18n("Hidden site to restore")
                }
                QQC2.Button {
                    text: i18n("Restore site")
                    icon.name: "edit-undo"
                    enabled: hiddenSites.currentIndex >= 0
                    onClicked: section.page.client.request("POST", "/web/site",
                        { url: hiddenSites.currentText, action: "unhide" }, () => section.page.reload(),
                        data => section.page.report(data.error || i18n("Could not restore this site."), true))
                }
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Offline Wikipedia")
        iconName: "documentation"

        WikipediaSetup {
            Layout.fillWidth: true
            page: section.page
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Connected tools")
        iconName: "plugins"

        QQC2.Label {
            visible: section.serverNames.length === 0
            text: i18n("No tools connected yet.")
            opacity: 0.7
        }

        Repeater {
            model: section.serverNames

            ColumnLayout {
                id: connected

                required property string modelData
                readonly property var entry: section.servers[modelData]
                property bool open: false

                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: "plugins"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: section.readable(connected.modelData)
                        opacity: connected.entry !== undefined && !connected.entry.enabled ? 0.5 : 1
                    }

                    QQC2.Label {
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
                    Layout.fillWidth: true
                    Layout.bottomMargin: Kirigami.Units.largeSpacing

                    sourceComponent: ToolServerDetails {
                        page: section.page
                        name: connected.modelData
                        entry: connected.entry
                    }
                }
            }
        }

        Flow {
            Layout.fillWidth: true
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
                height: Kirigami.Units.iconSizes.smallMedium
                width: height
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: !section.addingByHand && section.scanned && section.found.length === 0
            wrapMode: Text.Wrap
            opacity: 0.8
            text: i18n("Nothing more was found. Tools set up for other AI programs on this computer appear here.")
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: !section.addingByHand && section.found.length > 0
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: section.found

                ColumnLayout {
                    id: candidate

                    required property var modelData

                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: candidate.modelData.error.length > 0 ? "emblem-warning" : "plugins"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: section.readable(candidate.modelData.name)
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: candidate.modelData.error.length > 0
                                ? i18n("from %1, could not start", candidate.modelData.source)
                                : i18np("from %2, %1 tool", "from %2, %1 tools", candidate.modelData.tools.length,
                                        candidate.modelData.source)
                            font: Kirigami.Theme.smallFont
                            opacity: 0.6
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

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
                        Layout.fillWidth: true
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
            Layout.fillWidth: true
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
}
