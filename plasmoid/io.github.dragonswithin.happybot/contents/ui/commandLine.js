/*
    SPDX-License-Identifier: MIT
*/

/**
 * Converts between the one-line command a user types on the settings page
 * ("npx -y some-server --root '~/My Files'") and the `command` plus `args`
 * list a tool server is stored with (src/happy_bot/settings.py).
 *
 * The rules are a small, predictable subset of a POSIX shell: words split on
 * spaces and tabs; single quotes keep everything literally; double quotes
 * keep spaces and honour backslash before `"` and `\`; a backslash outside
 * quotes escapes the next character. Nothing is expanded (no `$VAR`, `~` or
 * globbing), because the daemon starts the server directly, not through a
 * shell. `join` quotes only words that need it, so `split(join(x))` gives
 * back `x`.
 */
.pragma library

function split(text) {
    const words = [];
    let word = "";
    let inWord = false;
    let quote = "";
    const source = String(text || "");
    for (let index = 0; index < source.length; index++) {
        const character = source[index];
        if (quote === "'") {
            if (character === "'") {
                quote = "";
            } else {
                word += character;
            }
        } else if (quote === "\"") {
            if (character === "\"") {
                quote = "";
            } else if (character === "\\" && (source[index + 1] === "\"" || source[index + 1] === "\\")) {
                word += source[++index];
            } else {
                word += character;
            }
        } else if (character === "'" || character === "\"") {
            quote = character;
            inWord = true;
        } else if (character === "\\" && index + 1 < source.length) {
            word += source[++index];
            inWord = true;
        } else if (character === " " || character === "\t") {
            if (inWord) {
                words.push(word);
                word = "";
                inWord = false;
            }
        } else {
            word += character;
            inWord = true;
        }
    }
    if (inWord) {
        words.push(word);
    }
    return words;
}

function quoteWord(word) {
    if (word.length > 0 && /^[A-Za-z0-9_@%+=:,.\/~-]+$/.test(word)) {
        return word;
    }
    return "'" + word.replace(/'/g, "'\\''") + "'";
}

function join(command, args) {
    return [command].concat(args || []).filter(word => word !== undefined).map(quoteWord).join(" ");
}
