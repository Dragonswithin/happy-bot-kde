// SPDX-License-Identifier: MIT
// The panel's icon button and search field share one face. Plasma's tray
// continues to use its named theme icon, including while recording.
pragma ComponentBehavior: Bound

import QtQuick
import org.kde.kirigami as Kirigami

Loader {
    id: icon

    property IconActivity activity
    property bool animateMascot: false
    property string robotStyle: "pip"
    property bool hovered: false
    required property string iconName

    sourceComponent: animateMascot && activity && Kirigami.Units.longDuration > 1
                     && visible && Window.window && Window.window.visible ? character : themedIcon

    Component {
        id: character
        MascotIcon {
            activity: icon.activity
            robotStyle: icon.robotStyle
        }
    }

    Component {
        id: themedIcon
        Kirigami.Icon {
            source: icon.iconName
            active: icon.hovered
        }
    }
}
