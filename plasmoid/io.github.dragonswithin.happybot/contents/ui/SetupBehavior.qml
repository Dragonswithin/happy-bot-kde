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
 *   plan to agree to, and `agent.local_only` (nothing leaves the computer).
 *   The wording mirrors the definition in docs/ROADMAP.md.
 * - Allowed actions: one switch per built-in action group; a group that is
 *   off is stored in `agent.disabled_tool_groups` and never offered to the
 *   model (src/happy_bot/tools/catalog.py). Reading the desktop and
 *   the user's connected tools are not switched here.
 * - Extras: `agent.load_plugins` (tools from the user's plugin files,
 *   src/happy_bot/tools/plugins.py) and `agent.serve_tools` (other AI
 *   programs may use the built-in tools through `happy-bot mcp-serve`).
 * - Your instructions: `agent.instructions`, added to the model's
 *   instructions for new conversations. Saved with its own button, since it
 *   is long text; "Restore suggested" puts back the daemon's starting text
 *   (`page.suggestedInstructions`) for the user to review and save.
 * - Limits: `agent.max_steps`, `agent.command_timeout_seconds` and
 *   `agent.notify_after_seconds`.
 * - Terminal: `agent.terminal`, chosen from the supported terminals the
 *   daemon found installed (`page.terminals`), or automatic.
 *
 * Ranges here mirror the validation in src/happy_bot/settings.py. The
 * section holds no state of its own; every change goes through `page.save`.
 */
Kirigami.FormLayout {
    id: section

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
        { name: "phone", label: i18n("Use your phone through KDE Connect (ring it, send to it, text messages)") },
        { name: "schedule", label: i18n("Set reminders and timers, keep notes and to-dos, and change your routines") },
    ]

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
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Approvals")
    }

    QQC2.RadioButton {
        Kirigami.FormData.label: i18n("Ask before it:")
        text: i18n("Deletes something or changes the operating system")
        checked: section.policy === "danger"
        onToggled: if (checked) section.setPolicy("danger")
    }

    QQC2.RadioButton {
        text: i18n("Changes anything at all")
        checked: section.policy === "changes"
        onToggled: if (checked) section.setPolicy("changes")
    }

    QQC2.RadioButton {
        text: i18n("Does anything, including looking things up")
        checked: section.policy === "everything"
        onToggled: if (checked) section.setPolicy("everything")
    }

    Hint {
        text: i18n("The first choice is recommended: everything else happens at once and is listed in the conversation as it runs.")
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Privacy:")
        text: i18n("Local only: nothing leaves this computer")
        checked: section.agent !== null && section.agent.local_only === true
        onToggled: section.setAgent("local_only", checked)
    }

    Hint {
        text: i18n("A hosted model is not used, and the assistant does not search the web or read web pages.")
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Plans:")
        text: i18n("Show me the plan before changing several things")
        checked: section.agent !== null && section.agent.confirm_plans === true
        onToggled: section.setAgent("confirm_plans", checked)
    }

    Hint {
        text: i18n("Anything it changes can be undone: ask it to undo, or ask what it did.")
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("What it may do")
    }

    // Repeated rows go inside one column: a Repeater placed directly in a
    // FormLayout can insert its rows after later siblings.
    ColumnLayout {
        Kirigami.FormData.label: i18n("Allow it to:")
        Kirigami.FormData.labelAlignment: Qt.AlignTop
        spacing: 0

        Repeater {
            model: section.groups

            QQC2.CheckBox {
                required property var modelData

                text: modelData.label
                checked: section.disabledGroups.indexOf(modelData.name) === -1
                onToggled: section.setGroup(modelData.name, checked)
            }
        }
    }

    Hint {
        text: i18n("It can always look at your windows, clipboard and files, and use the tools connected under Search & Tools. Switched-off abilities are never offered to the model.")
    }

    QQC2.CheckBox {
        Kirigami.FormData.label: i18n("Extras:")
        text: i18n("Load my own tools from the plugins folder")
        checked: section.agent !== null && section.agent.load_plugins === true
        onToggled: section.setAgent("load_plugins", checked)
    }

    QQC2.CheckBox {
        text: i18n("Let other AI programs on this computer use these tools")
        checked: section.agent !== null && section.agent.serve_tools === true
        onToggled: section.setAgent("serve_tools", checked)
    }

    Hint {
        text: i18n("Plugins are Python files in ~/.config/happy-bot/plugins. Other programs connect with the command happy-bot mcp-serve; anything that would need your approval is refused for them.")
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Your instructions")
    }

    QQC2.TextArea {
        id: instructions
        Kirigami.FormData.label: i18n("Always:")
        Layout.minimumWidth: Kirigami.Units.gridUnit * 20
        Layout.preferredHeight: Kirigami.Units.gridUnit * 6
        wrapMode: TextEdit.Wrap
        placeholderText: i18n("For example: Answer in German. I use Dolphin and Kate. Prefer Flatpak when installing.")
        text: section.agent ? section.agent.instructions : ""
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            text: i18n("Save instructions")
            icon.name: "document-save"
            enabled: section.agent !== null && instructions.text.trim() !== section.agent.instructions
            onClicked: section.setAgent("instructions", instructions.text.trim())
        }

        QQC2.Button {
            text: i18n("Restore suggested")
            icon.name: "edit-undo"
            enabled: (section.page.suggestedInstructions || "").length > 0
                && instructions.text !== section.page.suggestedInstructions
            onClicked: instructions.text = section.page.suggestedInstructions
        }

        QQC2.Label {
            text: i18n("%1 of 4000 characters", instructions.text.length)
            font: Kirigami.Theme.smallFont
            color: instructions.text.length > 4000 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            opacity: 0.7
        }
    }

    Hint {
        text: i18n("Your standing preferences, in your own words. Used from the next new conversation. They cannot switch off the approvals above.")
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Limits")
    }

    QQC2.SpinBox {
        Kirigami.FormData.label: i18n("Steps per request:")
        from: 5
        to: 200
        value: section.agent ? section.agent.max_steps : 40
        onValueModified: section.setAgent("max_steps", value)
    }

    Hint {
        text: i18n("How many times it may consult the model for one request. Operating another application takes several steps per click.")
    }

    QQC2.SpinBox {
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
        text: i18n("Unless the assistant asks for longer. Installs run in a terminal window and are not limited by this.")
    }

    QQC2.SpinBox {
        Kirigami.FormData.label: i18n("Notify when done after:")
        from: 0
        to: 3600
        stepSize: 10
        value: section.agent ? section.agent.notify_after_seconds : 60
        textFromValue: (value, locale) => value === 0 ? i18n("Never") : i18np("%1 second", "%1 seconds", value)
        valueFromText: (text, locale) => parseInt(text) || 0
        onValueModified: section.setAgent("notify_after_seconds", value)
    }

    Item {
        Kirigami.FormData.isSection: true
        Kirigami.FormData.label: i18n("Terminal")
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
        model: choices.map(name => name === "" ? i18n("Automatic (the system's default terminal)") : name)
        currentIndex: choices.indexOf(section.agent ? section.agent.terminal : "")
        onActivated: index => section.setAgent("terminal", terminal.choices[index])
    }

    Hint {
        text: i18n("Installs and anything that asks for your password open here, so you can watch and type.")
    }
}
