/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * Chooses by hand which tool fills a role (`file_search` or `web_search`),
 * shown under that role's row in SetupTools.qml. It is the manual route next
 * to the scan's "Use for…" suggestions, and covers every field of a
 * `roles.<role>` entry in src/happy_bot/settings.py: the server, the
 * tool, the argument that receives the typed text (`query_argument`) and,
 * when the tool has one, how many results to ask for (stored in
 * `arguments` under the tool's limit argument).
 *
 * A server's tools come from `GET /tools/servers?name=`, which starts the
 * server; each tool arrives with its arguments and the daemon's guess at
 * its query and limit arguments, used as the starting choice. Other fixed
 * arguments already stored for the same tool are kept.
 *
 * Nothing is stored until Save; `saved()` is emitted after it succeeded.
 */
GridLayout {
    id: editor

    required property var page
    required property string role
    required property var config

    readonly property var serverNames: page.settings
        ? Object.keys(page.settings.tool_servers).filter(name => page.settings.tool_servers[name].enabled).sort() : []
    property string serverName: ""
    property var tools: []
    property bool loading: false
    property string loadError: ""
    property string toolName: ""
    property string queryArgument: ""
    readonly property var tool: tools.find(item => item.name === toolName) || null
    readonly property var textArguments: tool ? tool.arguments.filter(item => item.type === "string").map(item => item.name) : []
    readonly property string limitArgument: tool ? tool.limit_argument : ""

    signal saved()

    columns: 2
    columnSpacing: Kirigami.Units.smallSpacing
    rowSpacing: Kirigami.Units.smallSpacing

    function loadTools(server) {
        editor.serverName = server;
        editor.tools = [];
        editor.loadError = "";
        if (!server) {
            return;
        }
        editor.loading = true;
        editor.page.client.request("GET", "/tools/servers?name=" + encodeURIComponent(server), null, function(data) {
            editor.loading = false;
            const found = (data.servers || [])[0];
            editor.tools = found ? found.tools : [];
            editor.loadError = found ? found.error : "";
            const keep = editor.config && editor.config.server === server ? editor.config.tool : "";
            editor.chooseTool(editor.tools.some(item => item.name === keep) ? keep : (editor.tools[0] ? editor.tools[0].name : ""));
        }, function(data) {
            editor.loading = false;
            editor.loadError = data.error || i18n("Could not list its tools");
        });
    }

    function chooseTool(name) {
        editor.toolName = name;
        const chosen = editor.tool;
        if (!chosen) {
            editor.queryArgument = "";
            return;
        }
        const sameTool = editor.config && editor.config.server === editor.serverName && editor.config.tool === name;
        editor.queryArgument = sameTool ? editor.config.query_argument
            : (chosen.query_argument || editor.textArguments[0] || "");
        limit.value = sameTool && chosen.limit_argument && editor.config.arguments[chosen.limit_argument] !== undefined
            ? editor.config.arguments[chosen.limit_argument] : 8;
    }

    Component.onCompleted: loadTools(editor.config ? editor.config.server : (editor.serverNames[0] || ""))

    QQC2.Label {
        text: i18n("Server:")
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.ComboBox {
            Layout.minimumWidth: Kirigami.Units.gridUnit * 12
            model: editor.serverNames
            currentIndex: editor.serverNames.indexOf(editor.serverName)
            onActivated: editor.loadTools(currentText)
        }

        QQC2.BusyIndicator {
            running: editor.loading
            visible: running
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
        }
    }

    QQC2.Label {
        Layout.columnSpan: 2
        visible: editor.serverNames.length === 0
        text: i18n("Connect a tool server first.")
        opacity: 0.7
    }

    QQC2.Label {
        Layout.columnSpan: 2
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        visible: editor.loadError.length > 0
        wrapMode: Text.Wrap
        text: editor.loadError
        color: Kirigami.Theme.negativeTextColor
    }

    QQC2.Label {
        text: i18n("Tool:")
    }

    QQC2.ComboBox {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
        model: editor.tools.map(item => item.name)
        currentIndex: editor.tools.findIndex(item => item.name === editor.toolName)
        onActivated: editor.chooseTool(currentText)
    }

    QQC2.Label {
        text: i18n("Text goes in:")
    }

    QQC2.ComboBox {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
        model: editor.textArguments
        currentIndex: editor.textArguments.indexOf(editor.queryArgument)
        onActivated: editor.queryArgument = currentText
    }

    QQC2.Label {
        visible: editor.limitArgument.length > 0
        text: i18n("Results:")
    }

    QQC2.SpinBox {
        id: limit
        visible: editor.limitArgument.length > 0
        from: 1
        to: 50
        value: 8
    }

    Item {
        Layout.preferredWidth: 1
    }

    QQC2.Button {
        text: i18n("Save")
        icon.name: "document-save"
        enabled: editor.tool !== null && editor.queryArgument.length > 0
        onClicked: {
            const sameTool = editor.config && editor.config.server === editor.serverName && editor.config.tool === editor.toolName;
            const arguments_ = sameTool ? Object.assign({}, editor.config.arguments) : {};
            delete arguments_[editor.queryArgument];
            if (editor.limitArgument) {
                arguments_[editor.limitArgument] = limit.value;
            }
            const entry = {
                server: editor.serverName, tool: editor.toolName, query_argument: editor.queryArgument, arguments: arguments_
            };
            const role = editor.role;
            editor.page.save(function(settings) { settings.roles[role] = entry; }, function() { editor.saved(); });
        }
    }
}
