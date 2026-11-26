/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3

/**
 * The panel search bar's results, shown right above the bar (beside it on
 * a side panel) while the user types there, like the application
 * launcher's search: an instant command, an answer and characters first,
 * then installed applications, settings pages, saved chats and files, with
 * an "Ask Happy Bot about …" row below. Before anything is typed it shows
 * what was used last as chips instead (`session.showingRecent`). main.qml
 * shows it only in the search-bar form, while the bar has the keyboard; the
 * popup and the floating Happy Bot do not search as the user types.
 *
 * It is a Plasma dialog that never takes the keyboard
 * (`Qt.WindowDoesNotAcceptFocus`, as Plasma's own panel-edit indicators
 * are), so typing stays in the bar: the bar's Down and Up move
 * `selectedIndex` (owned by main.qml) and its Enter opens the selected
 * result. Results can still be clicked. The list itself is FileResults.qml,
 * the same one the popup's file finder uses, and its signals are passed on
 * unchanged: `resultActivated(hit)`, `fileActionRequested(hit, action)` and
 * `askRequested(text)`. The dialog sizes to the list, at least the bar's
 * width and `minimumWidthInGridUnits`, at most `maximumHeightInGridUnits`
 * tall; longer lists scroll.
 */
PlasmaCore.Dialog {
    id: dialog

    required property var session
    property string query: ""
    property int selectedIndex: -1
    property string assistantIcon: ""
    property bool useRobotMascot: false
    property int minimumWidthInGridUnits: 24
    property int maximumHeightInGridUnits: 20

    signal resultActivated(var hit)
    signal fileActionRequested(var hit, string action)
    signal askRequested(string text)

    flags: Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
    hideOnWindowDeactivate: false

    backgroundHints: PlasmaCore.Dialog.NoBackground

    mainItem: AssistantSurface {
        id: surface
        accent: Look.assistantAccent(dialog.useRobotMascot, dialog.session.ui.robot_style ?? "pip",
                                     Kirigami.Theme.highlightColor)
        width: Math.max(dialog.visualParent ? dialog.visualParent.width : 0,
                        Kirigami.Units.gridUnit * dialog.minimumWidthInGridUnits)
        height: Math.round(Math.min(heading.height + results.naturalHeight + Kirigami.Units.smallSpacing,
                                   Kirigami.Units.gridUnit * dialog.maximumHeightInGridUnits))

        RowLayout {
            id: heading
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: surface.inset
            anchors.rightMargin: surface.inset
            height: Kirigami.Units.gridUnit * 1.5 + Math.ceil(Kirigami.Units.smallSpacing / 2)
            Kirigami.Icon {
                source: "folder-open-symbolic"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: i18n("Find a file")
                font.weight: Font.DemiBold
                Accessible.role: Accessible.Heading
            }
        }

        FileResults {
            id: results
            anchors.top: heading.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottomMargin: Kirigami.Units.smallSpacing

            session: dialog.session
            query: dialog.query
            selectedIndex: dialog.selectedIndex
            assistantIcon: dialog.assistantIcon
            useRobotMascot: dialog.useRobotMascot
            accent: surface.accent

            onResultActivated: hit => dialog.resultActivated(hit)
            onFileActionRequested: (hit, action) => dialog.fileActionRequested(hit, action)
            onAskRequested: text => dialog.askRequested(text)
        }
    }
}
