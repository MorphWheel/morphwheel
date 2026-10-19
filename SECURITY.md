# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting instead: open the
repository's **Security** tab and choose **Report a vulnerability**. We aim to acknowledge reports within a few days.

## What we consider in scope

- Anything that lets Morphwheel **modify, move or delete a source file**, or overwrite an existing file.
- Code execution through a crafted input file, for example through an image decoder.
- Bypassing the plugin trust prompt, or loading plugin code into the main (GUI) process.
- The opt-in engine downloads, for example HEIC support: integrity, hash pinning, and download location.

## Plugins are code

A Morphwheel plugin is Python code that runs with **your** user permissions. Plugins are disabled until
you enable them, and they run in separate worker processes. That isolation is for stability, not for
security. Only enable plugins from sources you trust.
