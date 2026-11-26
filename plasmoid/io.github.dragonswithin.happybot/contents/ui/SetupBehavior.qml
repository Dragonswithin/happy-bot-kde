/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The "Behaviour" page's section (ConfigBehavior.qml): how the assistant
 * carries out a request.
 *
 * - Approvals: the daemon's `approval_policy`, which actions pause for the
 *   user, and `agent.confirm_plans`, whether multi-step changes start with a
 *   plan to agree to, `agent.local_only` (nothing leaves the computer), and
 *   `agent.app_context`, which AI may see what is read from the application
 *   the user is in: AIs on this computer only, any AI, or none
 *   (src/happy_bot/app_context.py).
 *   The wording mirrors the definition in docs/ROADMAP.md.
 * - Allowed actions: one switch per built-in action group; a group that is
 *   off is stored in `agent.disabled_tool_groups` and never offered to the
 *   model (src/happy_bot/tools/catalog.py). Reading the desktop and
 *   the user's connected tools are not switched here.
 * - Typing into other apps: whether the desktop lets the assistant send
 *   key presses (`GET /typing`), and "Allow…", which shows Plasma's
 *   permission question now (`POST /typing/allow`, src/happy_bot/input_portal.py)
 *   instead of in the middle of a request. `typingAllowed` is the only
 *   state this section keeps, read when it opens.
 * - Extras: `agent.load_plugins` (tools from the user's plugin files,
 *   src/happy_bot/tools/plugins.py) and `agent.serve_tools` (other AI
 *   programs may use the built-in tools through `happy-bot mcp-serve`).
 * - Your instructions: `agent.instructions`, added to the model's
 *   instructions for new conversations. Saved with its own button, since it
 *   is long text; "Restore suggested" puts back the daemon's starting text
 *   (`page.suggestedInstructions`) for the user to review and save.
 * - Limits: `agent.max_steps` and `agent.command_timeout_seconds`.
 * - Notifications: whether a long request ends with a desktop notification
 *   and after how long (`agent.notify_after_seconds`; off is 0). Its icon
 *   follows `ui.robot_mascot` (src/happy_bot/ui_settings.py, `assistant_icon`).
 * - Terminal: `agent.terminal`, chosen from the supported terminals the
 *   daemon found installed (`page.terminals`), or automatic.
 *
 * Ranges here mirror the validation in src/happy_bot/settings.py. Apart
 * from `typingAllowed`, the section holds no state of its own; every
 * settings change goes through `page.save`.
 */
ColumnLayout {
    id: section
    spacing: Kirigami.Units.largeSpacing

    required property var page

    readonly property string policy: page.settings ? page.settings.approval_policy : "danger"
    // null until loaded, and from a daemon older than the `agent` settings.
    readonly property var agent: (page.settings && page.settings.agent) || null
    readonly property var disabledGroups: agent ? agent.disabled_tool_groups : []
    readonly property var groups: [
        { name: "windows", label: i18n("Move, arrange and close windows") },
        { name: "apps", label: i18n("Start applications") },
        { name: "gui", label: i18n("Press buttons and type in other applications") },
        { name: "system", label: i18n("Change sound, network, Bluetooth, displays, appearance and power") },
        { name: "files", label: i18n("Create, move, write and trash files") },
        { name: "shell", label: i18n("Run commands and open a terminal") },
        { name: "phone", label: i18n("Ring your phone, send files and text through KDE Connect") },
        { name: "schedule", label: i18n("Manage reminders, timers, notes, to-dos and routines") },
    ]

    property bool typingAllowed: false
    property bool askingTyping: false

    function readTyping() {
        section.page.client.request("GET", "/typing", null, data => section.typingAllowed = data.allowed === true, () => {});
    }

    function allowTyping() {
        section.askingTyping = true;
        section.page.client.request("POST", "/typing/allow", {}, function(data) {
            section.askingTyping = false;
            section.typingAllowed = data.allowed === true;
            section.page.report(i18n("Happy Bot may now type into other apps."), false);
        }, function(data) {
            section.askingTyping = false;
            section.page.report(data.error || i18n("Typing was not allowed"), true);
        });
    }

    Component.onCompleted: readTyping()

    function setPolicy(value) {
        if (value !== section.policy) {
            section.page.save(function(settings) { settings.approval_policy = value; });
        }
    }

    function setAgent(key, value) {
        if (section.agent && JSON.stringify(section.agent[key]) !== JSON.stringify(value)) {
            section.page.save(function(settings) { settings.agent[key] = value; });
        }
    }

    function setGroup(name, allowed) {
        const others = section.disabledGroups.filter(item => item !== name);
        section.setAgent("disabled_tool_groups", allowed ? others : others.concat([name]));
    }

    component Hint: QQC2.Label {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    component Choice: QQC2.RadioButton {
        id: choice
        Layout.fillWidth: true
        Layout.minimumWidth: 0

        // The desktop style elides radio labels, including the approval policy.
        Binding {
            target: choice.contentItem as Text
            property: "wrapMode"
            value: Text.Wrap
        }
    }

    readonly property QQC2.ButtonGroup approvalChoices: QQC2.ButtonGroup {}
    readonly property QQC2.ButtonGroup appContextChoices: QQC2.ButtonGroup {}

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Approvals")
        iconName: "security-high"
        description: i18n("Choose when Happy Bot asks before acting. The first option is recommended.")

        Choice {
            text: i18n("Before deletions or operating system changes")
            QQC2.ButtonGroup.group: section.approvalChoices
            checked: section.policy === "danger"
            onToggled: if (checked) section.setPolicy("danger")
        }

        Choice {
            text: i18n("Before any change")
            QQC2.ButtonGroup.group: section.approvalChoices
            checked: section.policy === "changes"
            onToggled: if (checked) section.setPolicy("changes")
        }

        Choice {
            text: i18n("Before every action, including lookups")
            QQC2.ButtonGroup.group: section.approvalChoices
            checked: section.policy === "everything"
            onToggled: if (checked) section.setPolicy("everything")
        }

        Kirigami.Separator { Layout.fillWidth: true }

        QQC2.CheckBox {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: i18n("Show me the plan before changing several things")
            checked: section.agent !== null && section.agent.confirm_plans === true
            onToggled: section.setAgent("confirm_plans", checked)
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Privacy")
        iconName: "preferences-desktop-user"

        QQC2.CheckBox {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: i18n("Local only")
            checked: section.agent !== null && section.agent.local_only === true
            onToggled: section.setAgent("local_only", checked)
        }

        Hint {
            text: i18n("Turns off hosted models, web search and web page reading.")
        }

        Kirigami.Separator { Layout.fillWidth: true }

        QQC2.Label {
            Layout.fillWidth: true
            text: i18n("Who can see details from the app you’re in?")
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }

        Choice {
            text: i18n("Only models on this computer")
            QQC2.ButtonGroup.group: section.appContextChoices
            checked: section.agent !== null && (section.agent.app_context || "local") === "local"
            onToggled: if (checked) section.setAgent("app_context", "local")
        }

        Choice {
            text: i18n("Any model, including online services")
            QQC2.ButtonGroup.group: section.appContextChoices
            checked: section.agent !== null && section.agent.app_context === "any"
            onToggled: if (checked) section.setAgent("app_context", "any")
        }

        Choice {
            text: i18n("No models")
            QQC2.ButtonGroup.group: section.appContextChoices
            checked: section.agent !== null && section.agent.app_context === "off"
            onToggled: if (checked) section.setAgent("app_context", "off")
        }

        Hint {
            text: i18n("App details include the name, version and window title. “Help with…” can also include selected text, visible controls and the open file. Models with image access can see the screenshot you preview before sending. Choose “No models” to turn off Help screenshots.")
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Allowed actions")
        iconName: "preferences-desktop-accessibility"
        description: i18n("Choose what Happy Bot can do. It can always read your windows, clipboard and files and use your connected tools.")

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            Repeater {
                model: section.groups

                QQC2.CheckBox {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0

                    text: modelData.label
                    checked: section.disabledGroups.indexOf(modelData.name) === -1
                    onToggled: section.setGroup(modelData.name, checked)
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: section.typingAllowed ? "checkmark" : "dialog-information"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: section.typingAllowed ? i18n("Keyboard control allowed") : i18n("Keyboard control needs permission")
            }

            QQC2.Button {
                visible: !section.typingAllowed
                text: section.askingTyping ? i18n("Waiting…") : i18n("Allow…")
                highlighted: true
                enabled: !section.askingTyping
                onClicked: section.allowTyping()
            }
        }

        Hint {
            visible: !section.typingAllowed
            text: i18n("Choose Allow to open Plasma’s keyboard permission dialog.")
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Your instructions")
        iconName: "document-edit"
        description: i18n("Write one preference per line. Saved instructions apply to new conversations and follow your approval settings.")

        QQC2.ScrollView {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: Kirigami.Units.gridUnit * 9
            clip: true
            QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff   // the text wraps

            QQC2.TextArea {
                id: instructions
                Accessible.name: i18n("Your instructions")
                wrapMode: TextEdit.Wrap
                placeholderText: i18n("For example, “Answer in German” or “Use Kate to edit files”.")
                text: section.agent ? section.agent.instructions : ""
            }
        }

        QQC2.Label {
            text: i18n("%1 of 4000 characters", instructions.text.length)
            font: Kirigami.Theme.smallFont
            color: instructions.text.length > 4000 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            opacity: 0.7
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width >= Kirigami.Units.gridUnit * 17 ? 2 : 1
            columnSpacing: Kirigami.Units.smallSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                text: i18n("Save instructions")
                icon.name: "document-save"
                enabled: section.agent !== null && instructions.text.trim() !== section.agent.instructions
                    && instructions.text.length <= 4000
                onClicked: section.setAgent("instructions", instructions.text.trim())
            }

            QQC2.Button {
                text: i18n("Restore suggested")
                icon.name: "edit-undo"
                enabled: (section.page.suggestedInstructions || "").length > 0
                    && instructions.text !== section.page.suggestedInstructions
                onClicked: instructions.text = section.page.suggestedInstructions
            }
        }

        Hint {
            text: i18n("Restore suggested fills the box with the original instructions for you to review before saving.")
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Notifications")
        iconName: "preferences-desktop-notification"

        QQC2.CheckBox {
            id: notifyWhenDone
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: i18n("Notify me when a long request finishes")
            checked: section.agent ? section.agent.notify_after_seconds > 0 : true
            // Off is stored as 0 seconds; on again starts from the daemon's default, a minute.
            onToggled: section.setAgent("notify_after_seconds", checked ? 60 : 0)
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.SpinBox {
                wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
                Kirigami.FormData.label: i18n("After:")
                visible: notifyWhenDone.checked
                from: 1
                to: 3600
                stepSize: 10
                value: section.agent && section.agent.notify_after_seconds > 0 ? section.agent.notify_after_seconds : 60
                textFromValue: (value, locale) => i18np("%1 second", "%1 seconds", value)
                valueFromText: (text, locale) => parseInt(text) || 1
                onValueModified: section.setAgent("notify_after_seconds", value)
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Request limits and terminal")
        iconName: "utilities-terminal"

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.SpinBox {
                wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
                Kirigami.FormData.label: i18n("Steps per request:")
                from: 5
                to: 200
                value: section.agent ? section.agent.max_steps : 40
                onValueModified: section.setAgent("max_steps", value)
            }

            Hint {
                text: i18n("Each step is one model call. Tasks in other applications can take several steps per click.")
            }

            QQC2.SpinBox {
                wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
                Kirigami.FormData.label: i18n("Commands may run for:")
                from: 5
                to: 1800
                stepSize: 5
                value: section.agent ? section.agent.command_timeout_seconds : 60
                textFromValue: (value, locale) => i18np("%1 second", "%1 seconds", value)
                valueFromText: (text, locale) => parseInt(text) || 5
                onValueModified: section.setAgent("command_timeout_seconds", value)
            }

            Hint {
                text: i18n("A command can request more time. Installs run in the terminal with no time limit.")
            }

            QQC2.ComboBox {
                id: terminal
                Kirigami.FormData.label: i18n("Open commands in:")
                Layout.minimumWidth: Kirigami.Units.gridUnit * 12
                readonly property var choices: {
                    const installed = section.page.terminals.slice();
                    const chosen = section.agent ? section.agent.terminal : "";
                    if (chosen && installed.indexOf(chosen) === -1) {
                        installed.push(chosen);
                    }
                    return [""].concat(installed);
                }
                model: choices.map(name => name === "" ? i18n("System default") : name)
                currentIndex: choices.indexOf(section.agent ? section.agent.terminal : "")
                onActivated: index => section.setAgent("terminal", terminal.choices[index])
            }

            Hint {
                text: i18n("Installs and anything that asks for your password open here, so you can watch and type.")
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: i18n("Tool sharing and plugins")
        iconName: "plugins"

        QQC2.CheckBox {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: i18n("Load my own tools from the plugins folder")
            checked: section.agent !== null && section.agent.load_plugins === true
            onToggled: section.setAgent("load_plugins", checked)
        }

        QQC2.CheckBox {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: i18n("Share tools with other AI programs on this computer")
            checked: section.agent !== null && section.agent.serve_tools === true
            onToggled: section.setAgent("serve_tools", checked)
        }

        Hint {
            text: i18n("Put Python plugins in ~/.config/happy-bot/plugins. Other programs connect with happy-bot mcp-serve and can only run tools that don’t require approval.")
        }
    }
}
