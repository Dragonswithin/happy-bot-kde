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
 * Every stored property of one connected tool server, shown when its row in
 * SetupTools.qml is expanded: whether it runs (`enabled`), whether the user
 * vouches that it only looks things up (`read_only`), the command that
 * starts it (`command` and `args`, edited as one line through
 * commandLine.js) and its environment (`env`, secret values, through
 * PairsEditor.qml), or for a server reached over HTTP its address (`url`)
 * and headers (`headers`, secret like the environment), and which of its tools the assistant may use (`tools`:
 * null for all, else a list of names).
 *
 * The tool list is fetched from the running server (`GET
 * /tools/servers?name=`), which starts it, so it is only loaded when the
 * user chooses to pick tools, and not for a server that is switched off.
 *
 * Every change is saved at once through `page.save`; this component keeps
 * only the fetched tool list.
 */
ColumnLayout {
    id: details

    required property var page
    required property string name
    required property var entry

    property var tools: []
    property bool loading: false
    property string loadError: ""

    spacing: Kirigami.Units.smallSpacing

    function update(mutate) {
        const name = details.name;
        details.page.save(function(settings) { mutate(settings.tool_servers[name]); });
    }

    /** Fetches the server's tools; `then(tools)` runs only when the listing worked. */
    function loadTools(then) {
        details.loading = true;
        details.loadError = "";
        details.page.client.request("GET", "/tools/servers?name=" + encodeURIComponent(details.name), null, function(data) {
            details.loading = false;
            const found = (data.servers || [])[0];
            details.tools = found ? found.tools : [];
            details.loadError = found ? found.error : "";
            if (then && details.loadError.length === 0) {
                then(details.tools);
            }
        }, function(data) {
            details.loading = false;
            details.loadError = data.error || i18n("Could not list its tools");
        });
    }

    Component.onCompleted: {
        if (details.entry.tools !== null && details.entry.enabled) {
            details.loadTools();
        }
    }

    QQC2.Switch {
        text: i18n("Running")
        checked: details.entry.enabled
        onToggled: details.update(server => { server.enabled = checked; })
    }

    QQC2.CheckBox {
        text: i18n("This server only reads information")
        checked: details.entry.read_only
        onToggled: details.update(server => { server.read_only = checked; })
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Tick this only if you are sure: its tools will then run without being treated as changes.")
    }

    readonly property bool remote: (details.entry.url || "").length > 0

    QQC2.Label {
        text: details.remote ? i18n("Address:") : i18n("Start command:")
    }

    QQC2.TextField {
        visible: details.remote
        Layout.fillWidth: true
        text: details.entry.url || ""
        onEditingFinished: {
            const wanted = text.trim();
            if (wanted !== details.entry.url) {
                details.update(server => { server.url = wanted; });
            }
        }
    }

    QQC2.TextField {
        visible: !details.remote
        Layout.fillWidth: true
        text: CommandLine.join(details.entry.command, details.entry.args)
        onEditingFinished: {
            const words = CommandLine.split(text);
            if (words.length === 0 || CommandLine.join(words[0], words.slice(1)) === CommandLine.join(details.entry.command, details.entry.args)) {
                return;
            }
            details.update(server => { server.command = words[0]; server.args = words.slice(1); });
        }
    }

    QQC2.Label {
        text: details.remote ? i18n("Headers:") : i18n("Environment:")
    }

    PairsEditor {
        Layout.fillWidth: true
        visible: !details.remote
        pairs: details.entry.env
        namePlaceholder: i18n("Variable")
        onEdited: changed => details.update(server => { server.env = changed; })
    }

    PairsEditor {
        Layout.fillWidth: true
        visible: details.remote
        pairs: details.entry.headers || ({})
        namePlaceholder: i18n("Header, e.g. Authorization")
        onEdited: changed => details.update(server => { server.headers = changed; })
    }

    QQC2.CheckBox {
        text: i18n("Let the assistant use all of its tools")
        enabled: details.entry.enabled && !details.loading
        checked: details.entry.tools === null
        onToggled: {
            if (checked) {
                details.update(server => { server.tools = null; });
            } else {
                // Start from every tool allowed, so nothing changes until the user unticks one.
                details.loadTools(tools => {
                    const names = tools.map(tool => tool.name);
                    details.update(server => { server.tools = names; });
                });
            }
        }
    }

    QQC2.Label {
        visible: !details.entry.enabled
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: i18n("Switch it on to choose which of its tools the assistant may use.")
        opacity: 0.7
    }

    QQC2.BusyIndicator {
        running: details.loading
        visible: running
        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
    }

    QQC2.Label {
        visible: details.loadError.length > 0
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        wrapMode: Text.Wrap
        text: details.loadError
        color: Kirigami.Theme.negativeTextColor
    }

    Repeater {
        model: details.entry.tools !== null && details.entry.enabled ? details.tools : []

        QQC2.CheckBox {
            required property var modelData

            Layout.leftMargin: Kirigami.Units.gridUnit
            text: String(modelData.name).replace(/_/g, " ")
            checked: details.entry.tools !== null && details.entry.tools.indexOf(modelData.name) !== -1
            QQC2.ToolTip.text: modelData.description
            QQC2.ToolTip.visible: hovered && modelData.description.length > 0
            onToggled: {
                const toolName = modelData.name;
                const wanted = checked;
                details.update(server => {
                    const allowed = (server.tools || []).filter(item => item !== toolName);
                    server.tools = wanted ? allowed.concat([toolName]) : allowed;
                });
            }
        }
    }
}
