/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * The welcome shown in a conversation that has nothing in it yet
 * (ResultsView.qml shows it while the conversation is open and empty): a
 * greeting with Happy Bot's picture (`assistantIcon`, tinted with `accent`),
 * a line on what it can do, and a few starting points (find a file, search
 * the web, desktop help, and System info when switched on), which the user
 * picks and orders in the settings (`buttons`, the `ui.start_screen`
 * setting); they stay square, in one row of three, or of four once there
 * are four or more. "Find a file" emits `findFilesChosen` and "Search the
 * web" `webSearchChosen`, which ResultsView.qml turns into its finders
 * (`AssistantSession.finder`: matching applications, settings and files, or
 * bookmarks, visited websites and web pages, show as the user types);
 * "System info" emits `systemInfoChosen`, which opens SystemInfoView.qml.
 * The others emit `promptChosen`
 * with the start of a request ("Help me with "), which ResultsView.qml
 * puts in the assistant's composer for them to finish. Nothing is sent until
 * they press Enter. The help shortcut names the application the user was in
 * (`helpWith`, `AssistantSession.helpWith`: "Help with Kate", with its
 * icon), so it is plain that Happy Bot knows which one; with none (opened
 * from the panel, or from the desktop itself) it is "Desktop help". Choosing
 * "Help with …" emits `helpChosen`, which also marks the chat so its requests
 * carry the application's full context (`AssistantSession.helpChat`). The
 * component keeps no state.
 */
ColumnLayout {
    id: welcome

    required property string assistantIcon
    property string robotStyle: "pip"
    required property color accent
    property bool animateGreeting: false
    // The application Happy Bot was opened from ({app, class, title}), or null.
    property var helpWith: null
    property string helpWithIcon: ""
    readonly property string appName: helpWith && helpWith.app ? helpWith.app : ""
    signal promptChosen(string prompt)
    signal findFilesChosen()
    signal webSearchChosen()
    signal systemInfoChosen()

    // The start screen's buttons, in the user's order (`ui.start_screen`, src/happy_bot/ui_settings.py).
    property var buttons: ["files", "web", "help"]
    readonly property var tiles: welcome.buttons.map(id => {
        switch (id) {
        case "files": return { label: i18n("Find a file"), icon: "folder-open-symbolic", prompt: "" };
        case "web": return { label: i18n("Search the web"), icon: "globe", prompt: "", web: true };
        case "system": return { label: i18n("System info"), icon: "speedometer", prompt: "", system: true };
        case "help": return welcome.appName
            ? { label: i18n("Help with %1", welcome.appName), icon: welcome.helpWithIcon || welcome.helpWith["class"],
                appIcon: true, help: true, prompt: i18n("In %1, help me", welcome.appName) }
            : { label: i18n("Desktop help"), icon: "computer-symbolic", prompt: i18n("Help me with") };
        default: return null;
        }
    }).filter(tile => tile !== null)
    // "Help with …": like promptChosen, and the chat it starts carries the application's full context.
    signal helpChosen(string prompt)

    spacing: Kirigami.Units.largeSpacing

    Rectangle {
        id: hero

        readonly property int inset: Kirigami.Units.gridUnit
        readonly property real artworkWidth: Math.min(width * 0.32, Kirigami.Units.gridUnit * 8)
        Layout.fillWidth: true
        implicitHeight: Math.max(Kirigami.Units.gridUnit * 6.5, intro.implicitHeight + inset * 2)
        radius: Kirigami.Units.cornerRadius * 3
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(welcome.accent, 0.06)) }
            GradientStop { position: 1; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(welcome.accent, 0.18)) }
        }
        border.color: Qt.alpha(welcome.accent, 0.23)

        ColumnLayout {
            id: intro
            anchors.left: parent.left
            anchors.leftMargin: hero.inset
            anchors.verticalCenter: parent.verticalCenter
            width: hero.width - hero.artworkWidth - hero.inset * 1.5
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: i18n("How can I help?")
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.65
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: i18n("Find files, explore the web, or get things done on your desktop.")
                opacity: 0.8
                wrapMode: Text.Wrap
            }
        }

        Item {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: hero.artworkWidth
            height: Math.min(parent.height - hero.inset, width)
            Accessible.ignored: true

            GreetingPortrait {
                anchors.centerIn: parent
                width: Math.min(parent.height, parent.width * 0.85)
                height: width
                iconSource: welcome.assistantIcon
                robotStyle: welcome.robotStyle
                accent: welcome.accent
                animate: welcome.animateGreeting
            }
        }
    }

    GridLayout {
        id: shortcuts
        Layout.fillWidth: true
        // Squares in one row: three columns, four once there are four or more buttons (more wrap), so
        // fewer buttons leave room instead of stretching wide.
        columns: width >= Kirigami.Units.gridUnit * 25 ? (welcome.tiles.length > 3 ? 4 : 3) : 1
        rowSpacing: Kirigami.Units.smallSpacing
        columnSpacing: Kirigami.Units.largeSpacing
        uniformCellWidths: true

        Repeater {
            model: welcome.tiles

            PlasmaComponents3.ItemDelegate {
                id: shortcut
                required property var modelData
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                padding: Kirigami.Units.largeSpacing * 1.5
                text: modelData.label
                onClicked: modelData.help ? welcome.helpChosen(modelData.prompt + " ")
                    : modelData.web ? welcome.webSearchChosen()
                    : modelData.system ? welcome.systemInfoChosen()
                    : modelData.prompt ? welcome.promptChosen(modelData.prompt + " ") : welcome.findFilesChosen()

                background: Rectangle {
                    radius: Kirigami.Units.cornerRadius * 2
                    color: Qt.alpha(shortcut.hovered || shortcut.down ? welcome.accent : Kirigami.Theme.textColor,
                                    shortcut.down ? 0.16 : shortcut.hovered ? 0.10 : 0.035)
                    border.color: shortcut.visualFocus ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.14)
                }
                contentItem: GridLayout {
                    columns: shortcuts.columns === 1 ? 2 : 1
                    rowSpacing: Kirigami.Units.largeSpacing
                    columnSpacing: Kirigami.Units.largeSpacing
                    Kirigami.Icon {
                        source: shortcut.modelData.icon
                        fallback: "computer-symbolic"
                        // An application's own icon keeps its colours; the symbolic ones take the accent.
                        isMask: !shortcut.modelData.appIcon
                        color: Qt.tint(Kirigami.Theme.textColor, Qt.alpha(welcome.accent, 0.55))
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: shortcut.text
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
