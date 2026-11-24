/*
    SPDX-License-Identifier: MIT
*/

/**
 * Optional prefixes in the search bar, for people who want to say what kind
 * of request they mean. They are never required: plain text goes to the
 * assistant on Enter, which decides what to do.
 *
 * - `?text`: on Enter, asks the assistant to answer from the web.
 * - `>text`: on Enter, asks the assistant to run `text` as a shell command
 *   (it still goes through the same approval rules).
 *
 * `parse(text)` returns `{mode, text}` with mode "all", "web" or "command" and the text without the prefix; `request(parsed)` is
 * the message sent to the assistant for it.
 */
.pragma library

function parse(text) {
    const value = String(text || "").trim();
    const modes = { "?": "web", ">": "command" };
    const mode = modes[value.charAt(0)];
    if (mode && value.length > 1) {
        return { mode: mode, text: value.substring(1).trim() };
    }
    return { mode: "all", text: value };
}

function request(parsed) {
    if (parsed.mode === "web") {
        return "Search the web and answer, with links: " + parsed.text;
    }
    if (parsed.mode === "command") {
        return "Run this shell command and show me its output: " + parsed.text;
    }
    return parsed.text;
}
