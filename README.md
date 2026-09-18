# 🐙 GitHub Manager Telegram Bot

A comprehensive, Telegram-based dashboard to manage GitHub repositories, files, branches, tags, and releases directly from your chat.

---

## 🌟 Core Features

### 📂 Repository Management
* **Interactive Browsing:** List all your repositories with built-in pagination (10 items per page) and quick-jump navigation.
* **Instant Search:** Find any public or private repository using keywords via `/search`.
* **Visibility Toggle:** Switch repository visibility between **Public 🔓** and **Private 🔒** with a single tap.
* **Repository Archiving:** Archive or unarchive repositories directly from the management menu, with safety locks that prevent accidental edits on read-only repositories.
* **Quick Administration:** Rename repositories, inspect metadata, or safely trigger repository deletions with double-confirmation safeguards.

---

### 🗂️ File & Media Editor
* **In-Chat Code Editing:** Browse files and directories, preview contents, and edit raw text or code files within Telegram's character limits.
* **Media Asset Replacement:** Detects non-text files (`.png`, `.jpg`, `.mp4`, `.mp3`, `.pdf`, etc.) and lets you overwrite them seamlessly.
* **Flexible Uploads:** Send replacement files either as uncompressed documents (original quality) or directly as regular compressed chat media (photos, videos, or audio messages).
* **New File Creation:** Add new files with custom paths and contents straight from the interface.

---

### 🚀 Release & Tag Dashboard
A dedicated release management subsystem featuring a dual-tab dashboard:

* **Releases Tab:**
  * Displays releases with automatic status indicators: **(Latest)**, **(Pre-release)**, or standard releases.
  * View release titles, target branch associations, version tags, and Markdown release notes.
  * Delete releases with confirmation prompts.
* **Tags Tab:**
  * View all repository git tags.
  * Delete remote git tags directly from repository history.

#### 📥 Asset Management
* **Direct Asset Links:** Access quick browser download links for any asset.
* **In-Chat Downloader:** Download release binaries and files directly into your Telegram chat window.
* **Asset Uploading & Deletion:** Attach new build artifacts to existing releases via `uploads.github.com` or delete outdated binaries.

#### ✏️ Full Release Editing
Modify existing releases on the fly:
* Shift the release's target Git tag.
* Update titles and changelog descriptions.
* Reclassify release labels dynamically (**None / Standard**, **Pre-release**, or **Latest Release**).

#### ✨ Step-by-Step Release Creation Wizard
An interactive 5-step guided creation flow:
1. **Tag Selection:** Pick an existing repository tag or manually type a new tag version (e.g., `v1.0.0`).
2. **Target Branch:** Select the target branch commit track.
3. **Release Title:** Set the headline label.
4. **Description:** Provide changelogs or release notes.
5. **Label & Assets:** Assign the classification status (**Standard**, **Pre-release**, or **Latest**) and optionally upload binary assets before publishing.
