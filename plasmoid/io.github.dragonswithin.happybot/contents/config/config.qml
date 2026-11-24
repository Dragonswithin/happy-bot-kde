/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

import org.kde.plasma.configuration
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

/**
 * Pages of the "Configure…" dialog. Nearly all of Happy Bot's settings
 * belong to the app (the widget run on its own by happy-bot-app, which
 * reports the "application" form factor), so which pages show depends on
 * the copy:
 *
 * - The app: Appearance (ConfigAppearance.qml: the mascot, the hotkey, the
 *   floating Happy Bot, the popup's size, and the panel widget's icon or
 *   search bar and its width) and the five
 *   pages for what the daemon stores (src/happy_bot/settings.py, each
 *   loaded and saved at once through DaemonSettings.qml): the AI models,
 *   search and tool servers, behaviour, history and folders, routines.
 * - The panel widget: only Panel (ConfigPanel.qml), which says that all of
 *   Happy Bot's settings are in the app and opens them. Plasma shows it only
 *   from its panel edit mode; the widget's own menu opens the app's.
 *
 * The first page is the one the dialog opens on, even when hidden, so it is
 * a single entry that is Appearance in the app and Panel in the panel.
 */
ConfigModel {
    id: pages

    readonly property bool app: Plasmoid.formFactor === PlasmaCore.Types.Application

    ConfigCategory {
        name: pages.app ? i18n("Appearance") : i18n("Panel")
        icon: pages.app ? "preferences-desktop-theme" : "panel"
        source: pages.app ? "ConfigAppearance.qml" : "ConfigPanel.qml"
    }
    ConfigCategory {
        name: i18n("AI Model")
        icon: "assistant"
        source: "ConfigModels.qml"
        visible: pages.app
    }
    ConfigCategory {
        name: i18n("Search & Tools")
        icon: "plugins"
        source: "ConfigTools.qml"
        visible: pages.app
    }
    ConfigCategory {
        name: i18n("Behaviour")
        icon: "preferences-system"
        source: "ConfigBehavior.qml"
        visible: pages.app
    }
    ConfigCategory {
        name: i18n("History & Folders")
        icon: "folder-open-recent"
        source: "ConfigHistory.qml"
        visible: pages.app
    }
    ConfigCategory {
        name: i18n("Routines & Reminders")
        icon: "chronometer"
        source: "ConfigRoutines.qml"
        visible: pages.app
    }
}
