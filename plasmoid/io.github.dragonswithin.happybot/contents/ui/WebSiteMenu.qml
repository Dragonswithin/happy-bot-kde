// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick.Controls as QQC2

// Both web result rows and start-page tiles edit the same homepage preference.
AssistantMenu {
    id: menu
    property var site: null
    signal siteActionRequested(var site, string action)

    QQC2.MenuItem {
        text: menu.site?.pinned ? i18n("Unpin site") : i18n("Pin site")
        icon.name: "pin"
        onTriggered: menu.siteActionRequested(menu.site, menu.site.pinned ? "unpin" : "pin")
    }
    QQC2.MenuItem {
        text: i18n("Never show in Frequent sites")
        icon.name: "visibility-hidden"
        onTriggered: menu.siteActionRequested(menu.site, "hide")
    }
}
