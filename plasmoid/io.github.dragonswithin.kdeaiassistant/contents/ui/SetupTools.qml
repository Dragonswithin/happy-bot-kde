/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * "Search and tools" section of ConfigSetup.qml: which tool does file search
 * and web search, which tool servers are connected, and a scan that offers
 * the servers the user already set up for other AI programs.
 *
 * A scan (`POST /tools/scan`) starts each discovered server briefly and
 * returns its tools and the roles it looks suited for. Choosing "Use for…"
 * imports the server and assigns that role in one step; "Add" imports it
 * without a role so the model can use its tools. Role suggestions are
 * guesses from the tool's wording and are only ever applied by the user.
 *
 * Durable changes go through `page.save` or `POST /tools/import`; this
 * component holds only the scan results.
 */
ColumnLayout {
    id: section

    required property var page

    readonly property var servers: page.settings ? page.settings.tool_servers : ({})
    readonly property var roles: page.settings ? page.settings.roles : ({})
    property var found: []
    property bool scanning: false
    property bool scanned: false

    spacing: Kirigami.Units.smallSpacing

    function roleLabel(role) {
        return role === "file_search" ? i18n("file search") : i18n("web search");
    }

    function roleText(role) {
        const config = section.roles[role];
        return config ? i18n("%1 (from %2)", config.tool, config.server) : i18n("not set up");
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
                section.page.report(i18n("Added %1.", server.name), false);
            }
        }, function(data) {
            section.page.report(data.error || i18n("Could not add %1", server.name), true);
        });
    }

    Kirigami.Heading {
        level: 3
        text: i18n("Search and tools")
    }

    Kirigami.FormLayout {
        Layout.fillWidth: true

        RowLayout {
            Kirigami.FormData.label: i18n("File search:")

            QQC2.Label {
                text: section.roleText("file_search")
            }

            QQC2.ToolButton {
                visible: section.roles.file_search !== undefined
                icon.name: "edit-clear"
                text: i18n("Stop using")
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: section.page.save(function(settings) { delete settings.roles.file_search; })
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Web search:")

            QQC2.Label {
                text: section.roleText("web_search")
            }

            QQC2.ToolButton {
                visible: section.roles.web_search !== undefined
                icon.name: "edit-clear"
                text: i18n("Stop using")
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: section.page.save(function(settings) { delete settings.roles.web_search; })
            }
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        opacity: 0.8
        text: i18n("File search shows matching files while you type. Web search lets the assistant answer with current information.")
    }

    Repeater {
        model: Object.keys(section.servers).sort()

        RowLayout {
            id: connected

            required property string modelData
            readonly property var entry: section.servers[modelData]

            Kirigami.Icon {
                source: "network-connect"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            QQC2.Label {
                Layout.fillWidth: true
                text: connected.entry && connected.entry.read_only
                    ? i18n("%1 (look-up only)", connected.modelData) : connected.modelData
                elide: Text.ElideRight
            }

            QQC2.Button {
                text: i18n("Remove")
                icon.name: "edit-delete"
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
    }

    RowLayout {
        QQC2.Button {
            text: i18n("Look for tools I already have")
            icon.name: "edit-find"
            enabled: !section.scanning
            onClicked: section.scan()
        }

        QQC2.BusyIndicator {
            running: section.scanning
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: section.scanned && section.found.length === 0
        wrapMode: Text.Wrap
        text: i18n("Nothing more was found. Tools set up for other AI programs on this computer appear here.")
    }

    Repeater {
        model: section.found

        ColumnLayout {
            id: candidate

            required property var modelData

            Layout.fillWidth: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true

                QQC2.Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: candidate.modelData.error.length > 0
                        ? i18n("%1 (from %2) could not be started", candidate.modelData.name, candidate.modelData.source)
                        : i18np("%2 (from %3): %1 tool", "%2 (from %3): %1 tools", candidate.modelData.tools.length,
                                candidate.modelData.name, candidate.modelData.source)
                }

                Repeater {
                    model: candidate.modelData.proposals

                    QQC2.Button {
                        required property var modelData
                        text: i18n("Use %1 for %2", modelData.config.tool, section.roleLabel(modelData.role))
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
