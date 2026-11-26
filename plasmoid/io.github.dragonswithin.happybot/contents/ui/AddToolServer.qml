/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import "commandLine.js" as CommandLine

/**
 * Form in SetupTools.qml for connecting a tool server (an MCP server) that
 * the scan did not find: a name, the command that starts it (one line, split
 * by commandLine.js) or, for one reached over HTTP, its web address, and
 * whether it only looks things up. Its environment, allowed tools and role
 * are set afterwards in its own details (ToolServerDetails.qml) and the
 * search rows.
 *
 * Adding stores a new `tool_servers` entry through `page.save`; the daemon
 * validates the name and command and starts the server when first needed.
 * `added(name)` is emitted after the save succeeded.
 */
ColumnLayout {
    id: form

    required property var page

    readonly property string serverName: name.text.trim()
    readonly property var words: CommandLine.split(commandLine.text)
    readonly property bool remote: /^https?:\/\/\S+$/.test(commandLine.text.trim())
    readonly property bool nameTaken: form.page.settings !== null
        && form.page.settings.tool_servers[form.serverName] !== undefined

    signal added(string name)

    spacing: Kirigami.Units.smallSpacing

    QQC2.Label {
        text: i18n("Name:")
    }

    QQC2.TextField {
        id: name
        Layout.fillWidth: true
        placeholderText: i18n("For example notes-search")
        validator: RegularExpressionValidator { regularExpression: /[A-Za-z0-9_.-]{0,64}/ }
    }

    QQC2.Label {
        visible: form.nameTaken
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: i18n("A tool server with this name is already connected.")
        color: Kirigami.Theme.negativeTextColor
    }

    QQC2.Label {
        text: i18n("Start command or web address:")
    }

    QQC2.TextField {
        id: commandLine
        Layout.fillWidth: true
        placeholderText: i18n("For example npx -y some-mcp-server, or https://example.com/mcp")
    }

    QQC2.CheckBox {
        id: readOnly
        text: i18n("This server only reads information")
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("The tool's own instructions give this command or address. API keys go in its Environment (or Headers, for an address) after adding it.")
    }

    QQC2.Button {
        text: i18n("Connect")
        icon.name: "list-add"
        enabled: form.serverName.length > 0 && !form.nameTaken && form.words.length > 0
        onClicked: {
            const serverName = form.serverName;
            const words = form.words;
            const vouched = readOnly.checked;
            const address = form.remote ? commandLine.text.trim() : "";
            form.page.save(function(settings) {
                settings.tool_servers[serverName] = address
                    ? { url: address, headers: {}, env: {}, args: [], enabled: true, read_only: vouched, tools: null }
                    : { command: words[0], args: words.slice(1), env: {}, enabled: true, read_only: vouched, tools: null };
            }, function() {
                name.text = "";
                commandLine.text = "";
                readOnly.checked = false;
                form.added(serverName);
            });
        }
    }
}
