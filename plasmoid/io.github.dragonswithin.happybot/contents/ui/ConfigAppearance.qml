/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.kquickcontrols
import org.kde.plasma.plasmoid

/**
 * "Appearance" page of the Happy Bot app's settings dialog: how Happy Bot
 * looks and behaves, in the app and in the panel widget alike.
 *
 * - Look and feel (the daemon's `ui` settings, src/happy_bot/ui_settings.py):
 *   the mascot or the wand, the floating Happy Bot's look (shortcut size, how faded while
 *   not in use, back to its corner), the popup's size, the start screen's
 *   buttons and their order (StartScreenButtons.qml), mascot motion and sounds.
 *   They are read from `GET /health` and each change is saved
 *   at once with `POST /ui`, so the panel widget, which reads the same
 *   values, always matches the app.
 * - The app itself (`GET /app`, `POST /app`, src/happy_bot/app_control.py):
 *   whether it starts at login, read again every few seconds.
 * - The hotkey: this app copy's global shortcut (`Plasmoid.globalShortcut`),
 *   stored in `saveConfig` when the user applies, as on Plasma's Keyboard
 *   Shortcuts page. It opens the floating Happy Bot knowing which
 *   application the user is in.
 * - The panel widget's look (`GET`/`POST /panel`, src/happy_bot/panel_widget.py):
 *   the icon or a search bar, and the bar's width. They are that widget's own
 *   Plasma settings, changed at once through the Plasma shell, so Happy Bot
 *   has this one settings dialog; the widget's own page only points here.
 *
 * `cfg_daemonUrl` (no field: the address is found by itself) is only read, so
 * this page talks to the daemon the copy was set up for. The page keeps only
 * what it shows: the values read, the app's state and the panel widgets.
 */
KCM.SimpleKCM {
    id: page

    property string cfg_daemonUrl: ""
    signal previewWaveRequested()

    property bool unsavedChanges: false
    property var ui: null
    property bool appAutostart: false
    property var panelWidgets: []  // [{id, search_bar, bar_width, vertical}], from GET /panel
    readonly property bool onPanel: panelWidgets.length > 0
    readonly property bool searchBar: panelWidgets.some(widget => widget.search_bar)
    property string problem: ""

    function saveConfig() {
        Plasmoid.globalShortcut = hotkey.keySequence;
        page.unsavedChanges = false;
    }

    function read() {
        client.request("GET", "/health", null, function(data) {
            page.ui = data.ui || null;
        }, function(data) {
            page.problem = data.error || i18n("The assistant is not running");
        });
    }

    function save(changes) {
        client.request("POST", "/ui", { changes: changes }, function(data) {
            page.ui = data.ui;
            page.problem = "";
        }, function(data) {
            page.problem = data.error || i18n("That could not be saved");
            page.read();
        });
    }

    function readPanel() {
        client.request("GET", "/panel", null, data => page.panelWidgets = data.widgets || [], () => page.panelWidgets = []);
    }

    function changePanel(changes) {
        client.request("POST", "/panel", changes, function(data) {
            page.panelWidgets = data.widgets || [];
            page.problem = "";
        }, function(data) {
            page.problem = data.error || i18n("The panel could not be changed");
            page.readPanel();
        });
    }

    function readApp() {
        client.request("GET", "/app", null, data => page.appAutostart = data.autostart === true, () => {});
    }

    DaemonClient {
        id: client
        configuredUrl: page.cfg_daemonUrl || ""
    }

    Component.onCompleted: {
        page.read();
        page.readPanel();
    }

    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: page.readApp()
    }

    component PictureChoice: QQC2.RadioDelegate {
        id: choice

        Layout.fillWidth: true
        Layout.minimumWidth: 0
        icon.width: Kirigami.Units.iconSizes.medium
        icon.height: Kirigami.Units.iconSizes.medium
        padding: Kirigami.Units.largeSpacing
        bottomPadding: padding
        leftInset: 0
        rightInset: 0
        topInset: 0
        bottomInset: 0

        background: Rectangle {
            radius: Kirigami.Units.cornerRadius * 2
            color: Qt.alpha(Kirigami.Theme.highlightColor, choice.checked ? 0.12 : choice.hovered ? 0.06 : 0)
            border.color: choice.visualFocus || choice.checked
                          ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.16)
            border.width: choice.visualFocus ? 2 : 1
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.problem.length > 0
            type: Kirigami.MessageType.Error
            text: page.problem
            actions: [
                Kirigami.Action {
                    visible: page.ui === null
                    text: i18n("Try again")
                    icon.name: "view-refresh"
                    onTriggered: {
                        page.problem = "";
                        page.read();
                        page.readPanel();
                    }
                }
            ]
        }

        SettingsSection {
            Layout.fillWidth: true
            enabled: page.ui !== null
            title: i18n("Happy Bot’s picture")
            iconName: "preferences-desktop-icons"
            description: i18n("Choose the picture you see in the panel, on the floating button and beside replies.")
            headerArtwork: GreetingPortrait {
                id: picturePreview
                iconSource: Look.assistantIcon(page.ui?.robot_mascot ?? true)
                animate: page.ui?.robot_mascot === true && page.ui?.mascot_animations !== false
                Connections {
                    target: page
                    function onPreviewWaveRequested() { picturePreview.greet(); }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width >= Kirigami.Units.gridUnit * 17 ? 2 : 1
                uniformCellWidths: true
                rowSpacing: Kirigami.Units.smallSpacing
                columnSpacing: Kirigami.Units.largeSpacing

                PictureChoice {
                    text: i18n("Robot")
                    icon.source: Look.robotIcon
                    checked: page.ui !== null && page.ui.robot_mascot
                    onClicked: if (!page.ui.robot_mascot) page.save({ robot_mascot: true })
                }
                PictureChoice {
                    text: i18n("Wand")
                    icon.name: "tools-wizard"
                    checked: page.ui !== null && !page.ui.robot_mascot
                    onClicked: if (page.ui.robot_mascot) page.save({ robot_mascot: false })
                }
            }

            RowLayout {
                Layout.fillWidth: true
                QQC2.CheckBox {
                    id: animateRobot
                    enabled: page.ui?.robot_mascot === true
                    text: i18n("Animate the robot")
                    checked: page.ui !== null && page.ui.mascot_animations !== false
                    onToggled: page.save({ mascot_animations: checked })
                }
                QQC2.ToolButton {
                    enabled: animateRobot.enabled && animateRobot.checked && Kirigami.Units.longDuration > 1
                    text: i18n("Replay wave")
                    icon.name: "media-playback-start"
                    onClicked: page.previewWaveRequested()
                }
            }

            QQC2.CheckBox {
                text: i18n("Show helpful nudges")
                checked: page.ui !== null && page.ui.mascot_nudges !== false
                onToggled: page.save({ mascot_nudges: checked })
            }

            RowLayout {
                Layout.fillWidth: true

                QQC2.CheckBox {
                    text: i18n("Play a greeting sound")
                    checked: page.ui !== null && page.ui.robot_sounds === true
                    onToggled: page.save({ robot_sounds: checked })
                }

                QQC2.ToolButton {
                    text: i18n("Preview")
                    Accessible.name: i18n("Preview greeting sound")
                    icon.name: "media-playback-start"
                    onClicked: feedback.greet()
                }

                RobotFeedback {
                    id: feedback
                    onUnavailable: page.problem = i18n("The greeting could not play. Check your audio output and that Qt Multimedia is installed.")
                }
            }
        }

        SettingsSection {
            Layout.fillWidth: true
            enabled: page.ui !== null
            title: i18n("Start screen")
            iconName: "view-grid"
            description: i18n("Choose which buttons appear when Happy Bot opens. Use the arrows to change their order.")

            StartScreenButtons {
                Layout.fillWidth: true
                settingsPage: page
            }
        }

        SettingsSection {
            Layout.fillWidth: true
            enabled: page.ui !== null
            title: i18n("Floating Happy Bot")
            iconName: "window-keep-above"
            description: i18n("Open Happy Bot over the app you’re using. Drag the floating button to move it.")

            QQC2.CheckBox {
                text: i18n("Start Happy Bot at login")
                checked: page.appAutostart
                onToggled: client.request("POST", "/app", { autostart: checked },
                                          data => page.appAutostart = data.autostart === true, () => page.readApp())
            }

            Kirigami.FormLayout {
                Layout.fillWidth: true

                KeySequenceItem {
                    id: hotkey
                    Kirigami.FormData.label: i18n("Keyboard shortcut:")
                    keySequence: Plasmoid.globalShortcut
                    patterns: ShortcutPattern.Modifier | ShortcutPattern.ModifierAndKey
                    onKeySequenceModified: page.unsavedChanges = keySequence !== Plasmoid.globalShortcut
                }

                QQC2.SpinBox {
                    Kirigami.FormData.label: i18n("Shortcut size:")
                    Accessible.name: i18n("Floating shortcut size")
                    wheelEnabled: false
                    from: 50
                    to: 200
                    stepSize: 10
                    value: page.ui?.floating_size ?? 100
                    textFromValue: (number, locale) => i18n("%1%", number)
                    onValueModified: page.save({ floating_size: value })
                }

                RowLayout {
                    Kirigami.FormData.label: i18n("Idle opacity:")

                    QQC2.Slider {
                        id: floatingOpacity
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 8
                        Accessible.name: i18n("Idle opacity")
                        from: 15
                        to: 100
                        stepSize: 5
                        value: page.ui !== null ? page.ui.floating_opacity : 40
                        onPressedChanged: if (!pressed) page.save({ floating_opacity: Math.round(value) })
                    }

                    QQC2.Label { text: i18n("%1%", Math.round(floatingOpacity.value)) }
                }

                QQC2.Button {
                    Kirigami.FormData.label: i18n("Position:")
                    enabled: page.ui !== null && (page.ui.floating_x >= 0 || page.ui.floating_y >= 0)
                    text: i18n("Return to corner")
                    icon.name: "edit-undo"
                    onClicked: page.save({ floating_x: -1, floating_y: -1 })
                }
            }
        }

        SettingsSection {
            Layout.fillWidth: true
            enabled: page.ui !== null
            title: i18n("Panel widget")
            iconName: "preferences-desktop-plasma"
            description: page.onPanel
                ? i18n("On a horizontal panel you can type directly into a search bar. Vertical panels always show the icon.")
                : i18n("To add Happy Bot to your panel, right-click the panel, choose Add Widgets… and drag Happy Bot onto it.")

            Kirigami.FormLayout {
                Layout.fillWidth: true
                visible: page.onPanel

                QQC2.RadioButton {
                    Kirigami.FormData.label: i18n("Show:")
                    text: i18n("Happy Bot’s icon")
                    checked: page.onPanel && !page.searchBar
                    onToggled: if (checked) page.changePanel({ search_bar: false })
                }
                QQC2.RadioButton {
                    text: i18n("Search bar")
                    checked: page.searchBar
                    onToggled: if (checked) page.changePanel({ search_bar: true })
                }
                QQC2.SpinBox {
                    wheelEnabled: false
                    visible: page.searchBar
                    Kirigami.FormData.label: i18n("Width in font units:")
                    from: 8
                    to: 60
                    value: page.onPanel ? page.panelWidgets[0].bar_width : 18
                    onValueModified: page.changePanel({ bar_width: value })
                }
            }
        }

        SettingsSection {
            Layout.fillWidth: true
            enabled: page.ui !== null
            title: i18n("Popup size")
            iconName: "transform-scale"
            description: i18n("The floating button and panel open the same size popup. Dimensions scale with your desktop font.")

            Kirigami.FormLayout {
                Layout.fillWidth: true

                QQC2.SpinBox {
                    wheelEnabled: false
                    Kirigami.FormData.label: i18n("Width:")
                    from: 20
                    to: 70
                    value: page.ui !== null ? page.ui.popup_width : 30
                    onValueModified: page.save({ popup_width: value })
                }
                QQC2.SpinBox {
                    wheelEnabled: false
                    Kirigami.FormData.label: i18n("Height:")
                    from: 12
                    to: 50
                    value: page.ui !== null ? page.ui.popup_height : 26
                    onValueModified: page.save({ popup_height: value })
                }
            }
        }
    }
}
