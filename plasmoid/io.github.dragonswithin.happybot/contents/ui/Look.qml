/*
    SPDX-License-Identifier: MIT
*/

pragma Singleton

import QtCore as QtCore
import QtQuick

/**
 * Shared presentation helpers for the applet: which icon stands for the
 * assistant (`assistantIcon`: the wand, or the robot mascot `robotIcon`
 * when the `useRobotMascot` setting is on), which icon stands for a search
 * hit, which kind of result it is and its heading (`hitGroup`,
 * `hitGroupTitle`, `groupHits`), how to show a path compactly, and the tint
 * used for cards. Pure
 * functions and constants only; no state and no requests. Registered as a
 * singleton in qmldir so every view formats things the same way.
 */
QtObject {
    readonly property string homePath: String(QtCore.StandardPaths.writableLocation(
        QtCore.StandardPaths.HomeLocation)).replace(/^file:\/\//, "")

    readonly property url robotIcon: Qt.resolvedUrl("../images/happy-bot.svg")

    readonly property url microphoneIcon: Qt.resolvedUrl("../images/microphone.svg")

    function assistantIcon(useRobotMascot: bool): string {
        return useRobotMascot ? robotIcon.toString() : "tools-wizard";
    }

    readonly property var extensionIcons: ({
        pdf: "application-pdf", md: "text-x-markdown", txt: "text-plain", log: "text-x-log",
        py: "text-x-python", js: "text-x-javascript", ts: "text-x-typescript", qml: "text-x-qml",
        java: "text-x-java", c: "text-x-csrc", h: "text-x-chdr", cpp: "text-x-c++src", rs: "text-x-rust",
        sh: "application-x-shellscript", json: "application-json", xml: "application-xml",
        yml: "application-x-yaml", yaml: "application-x-yaml", toml: "text-x-generic", ini: "text-x-generic",
        conf: "text-x-generic", csv: "text-csv", html: "text-html", css: "text-css",
        png: "image-png", jpg: "image-jpeg", jpeg: "image-jpeg", gif: "image-gif", svg: "image-svg+xml",
        webp: "image-webp", mp3: "audio-mpeg", flac: "audio-flac", opus: "audio-x-generic", ogg: "audio-ogg",
        mp4: "video-mp4", mkv: "video-x-matroska", webm: "video-webm", zip: "application-zip",
        gz: "application-x-gzip", tar: "application-x-tar", jar: "application-x-java-archive",
        doc: "application-msword", docx: "application-vnd.openxmlformats-officedocument.wordprocessingml.document",
        xls: "application-vnd.ms-excel", xlsx: "application-vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        odt: "application-vnd.oasis.opendocument.text", ods: "application-vnd.oasis.opendocument.spreadsheet",
        desktop: "application-x-desktop"
    })

    function hitIcon(hit) {
        if (hit.kind === "quick") {
            return hit.icon || "system-run";
        }
        if (hit.kind === "folder") {
            return "folder";
        }
        if (hit.kind === "link") {
            return "internet-web-browser";
        }
        const dot = hit.location.lastIndexOf(".");
        const extension = dot > hit.location.lastIndexOf("/") ? hit.location.substring(dot + 1).toLowerCase() : "";
        return extensionIcons[extension] || "text-x-generic";
    }

    // The kinds of search result, in the order they are listed under their headings (FileResults.qml).
    readonly property var hitGroups: ["answer", "applications", "settings", "chats", "files"]

    /** Which kind of result a hit is: a quick result by its action, anything from the file search "files". */
    function hitGroup(hit) {
        if (!hit) {
            return "";
        }
        if (hit.kind !== "quick") {
            return "files";
        }
        const groups = { copy: "answer", launch: "applications", settings: "settings", conversation: "chats" };
        return groups[hit.action ? hit.action.type : ""] || "applications";
    }

    /** The heading over a kind of result. */
    function hitGroupTitle(group) {
        switch (group) {
        case "answer": return i18n("Answer");
        case "applications": return i18n("Applications");
        case "settings": return i18n("Settings");
        case "chats": return i18n("Saved chats");
        default: return i18n("Files");
        }
    }

    /** `hits` with each kind together, in `hitGroups` order (applications first); the order within a kind is kept. */
    function groupHits(hits) {
        const order = hitGroups;
        return hits.map((hit, position) => ({ hit: hit, position: position }))
            .sort((a, b) => (order.indexOf(hitGroup(a.hit)) - order.indexOf(hitGroup(b.hit))) || (a.position - b.position))
            .map(item => item.hit);
    }

    /** The folder a hit is in, with the home folder shown as ~. Links show their host. Quick results show
     *  their detail without the kind ("Application · Minecraft launcher" shows "Minecraft launcher"), which
     *  their heading already says; an answer keeps its whole line. */
    function hitWhere(hit) {
        if (hit.kind === "quick") {
            const subtitle = hit.subtitle || "";
            if (hitGroup(hit) === "answer") {
                return subtitle;
            }
            const parts = subtitle.split(" · ");
            return parts.length > 1 ? parts.slice(1).join(" · ") : "";
        }
        if (hit.kind === "link") {
            const match = hit.location.match(/^https?:\/\/([^\/]+)/);
            return match ? match[1] : hit.location;
        }
        const folder = hit.location.substring(0, hit.location.lastIndexOf("/")) || "/";
        return shortPath(folder);
    }

    /** "14:05" today, "Yesterday", the weekday within a week, else the date. */
    function when(seconds) {
        const then = new Date(seconds * 1000);
        const now = new Date();
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const days = Math.floor((startOfToday - new Date(then.getFullYear(), then.getMonth(), then.getDate())) / 86400000);
        if (days <= 0) {
            return then.toLocaleTimeString(Qt.locale(), Locale.ShortFormat);
        }
        if (days === 1) {
            return i18n("Yesterday");
        }
        if (days < 7) {
            return Qt.locale().dayName(then.getDay(), Locale.LongFormat);
        }
        return then.toLocaleDateString(Qt.locale(), Locale.ShortFormat);
    }

    function shortPath(path) {
        if (homePath && (path === homePath || path.startsWith(homePath + "/"))) {
            return "~" + path.substring(homePath.length);
        }
        return path;
    }
}
