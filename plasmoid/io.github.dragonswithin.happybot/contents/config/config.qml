/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

import org.kde.plasma.configuration

/**
 * Pages shown in the applet's "Configure…" dialog. Every setting the
 * assistant has is on one of them, so nobody needs to edit a file.
 *
 * The first five hold what the daemon stores in its one settings file
 * (src/happy_bot/settings.py), each loaded and saved at once through
 * DaemonSettings.qml: the model, search and tool servers, behaviour,
 * history and folders, and routines (with the reminders that are set). "Search Bar" holds the applet's own Plasma settings
 * declared in main.xml. Plasma adds its Keyboard Shortcuts page, where the
 * user sets the shortcut that opens the assistant.
 */
ConfigModel {
    ConfigCategory {
        name: i18n("AI Model")
        icon: "assistant"
        source: "ConfigModels.qml"
    }
    ConfigCategory {
        name: i18n("Search & Tools")
        icon: "plugins"
        source: "ConfigTools.qml"
    }
    ConfigCategory {
        name: i18n("Behaviour")
        icon: "preferences-system"
        source: "ConfigBehavior.qml"
    }
    ConfigCategory {
        name: i18n("History & Folders")
        icon: "folder-open-recent"
        source: "ConfigHistory.qml"
    }
    ConfigCategory {
        name: i18n("Routines & Reminders")
        icon: "chronometer"
        source: "ConfigRoutines.qml"
    }
    ConfigCategory {
        name: i18n("Search Bar")
        icon: "search"
        source: "ConfigGeneral.qml"
    }
}
