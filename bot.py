import logging
import requests
import base64
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from warnings import filterwarnings
from telegram.warnings import PTBUserWarning

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TOKEN")
# States
(LOGIN, CREATE_NAME, SEARCH_QUERY, REPO_MANAGE, RENAME_REPO, NEW_FILE_PATH, NEW_FILE_CONTENT, EDIT_FILE_CONTENT, RENAME_FILE_NEW_NAME, CONFIRM_ACTION, RELEASE_MENU, CHOOSE_RELEASE, CHOOSE_TAG, EDIT_RELEASE_MENU, EDIT_TEXT_FIELD, SAVE_TAG_SHIFT_MANUAL, CONFIRM_RELEASE_DEL, CONFIRM_ASSET_DEL, CREATE_REL_TAG, CREATE_REL_TARGET, CREATE_REL_TITLE, CREATE_REL_DESC, CREATE_REL_LABEL, CREATE_REL_ASSETS, CREATE_REL_TAG_MANUAL) = range(25)
 

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active.")

def run_health_server():
    httpd = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    httpd.serve_forever()

# --- Helpers ---
def github_req(method, endpoint, token, data=None):
    url = f"https://api.github.com{endpoint}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    return requests.request(method, url, headers=headers, json=data)

def get_repo_markup(repos, page=1, items_per_page=10):
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    current_batch = repos[start_index:end_index]
    
    total_pages = (len(repos) + items_per_page - 1) // items_per_page
    if total_pages == 0: total_pages = 1

    keyboard = [[InlineKeyboardButton((r['full_name']).rsplit('/')[-1], callback_data=f"sel_{r['full_name']}")] for r in current_batch]
    
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))
    else:
        nav_row.append(InlineKeyboardButton("🚩", callback_data="ignore"))

    nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))

    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))
    else:
        nav_row.append(InlineKeyboardButton("🏁", callback_data="ignore"))

    keyboard.append(nav_row)
    return keyboard

def get_search_repo_markup(repos, prefix="sea_"):
    keyboard = [[InlineKeyboardButton(r['full_name'], callback_data=f"{prefix}{r['full_name']}")] for r in repos[:15]]
    return keyboard

def format_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

# --- Entry Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /login to provide your GitHub PAT.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_state = context.user_data.get('user_state')
        cancel_map = {
            RENAME_REPO: send_repo_management_menu(update, query, context),
            NEW_FILE_PATH: send_repo_management_menu(update, query, context),
            EDIT_FILE_CONTENT: view_item_callback(update, context),
            RENAME_FILE_NEW_NAME: view_item_callback(update, context),
            SAVE_TAG_SHIFT_MANUAL: show_tags_for_release_edit(update, query, context)
        }
        return await cancel_map.get(user_state)
    except:
        await update.message.reply_text(
            "❌ Action closed.\n\n"
            "Available commands:\n"
            "/repositories - Browse and manage your repositories\n"
            "/search - Search repository with specific word\n"
            "/create - Create a new repository"
        )
        return ConversationHandler.END
    
# --- Login Flow ---
async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'token' in context.user_data:
        await update.message.reply_text("You are already logged in!")
    else:
        await update.message.reply_text("🔑 Please send your GitHub Personal Access Token (PAT):")
        return LOGIN

async def login_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text
    res = github_req("GET", "/user", token)
    if res.status_code == 200:
        context.user_data['token'] = token
        await update.message.reply_text(f"✅ Logged in as {res.json()['login']}!\n\nIf you want to logout, send /logout.")
        return ConversationHandler.END
    await update.message.reply_text("❌ Invalid Token. Use /login to try again.")
    return ConversationHandler.END

async def logout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'token' in context.user_data:
        kb = [
            [InlineKeyboardButton("⚠️ Yes, I'm sure!", callback_data="conf_pat_yes")],
            [InlineKeyboardButton("❌ Cancel", callback_data="conf_pat_no")]
        ]
        await update.message.reply_text(
            "⚠️ *Are you sure you want to logout?*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return CONFIRM_ACTION
    else:
        await update.message.reply_text("You are not currently logged in.")

# --- List & Search ---
async def repositories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.user_data.get('token')
    if not token:
        await update.message.reply_text("Please /login first.")
        return ConversationHandler.END
    if 'search_repo' in context.user_data:
        del context.user_data['search_repo']
    if context.user_data.get('now_page'):
        del context.user_data['now_page']

    res = github_req("GET", "/user/repos?sort=updated&per_page=100", token)
    all_repos = res.json()
    context.user_data['all_repos_cache'] = all_repos
    
    text = "📂 Select a repository:"
    keyboard = get_repo_markup(all_repos, page=1)
    keyboard += [[InlineKeyboardButton("❌ Close", callback_data="m_close")]]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return REPO_MANAGE

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Enter repo name keyword:\n\nOr /cancel ❌")
    return SEARCH_QUERY

async def search_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.user_data['token']
    res = github_req("GET", "/user/repos?per_page=100", token)
    if update.message:
        context.user_data['search_repo'] = update.message.text
    search_repo = context.user_data['search_repo']
    matches = [r for r in res.json() if search_repo.lower() in r['name'].lower()]
    
    if not matches:
        await update.message.reply_text("No matches found.")
        return ConversationHandler.END

    keyboard = get_search_repo_markup(matches)
    keyboard += [[InlineKeyboardButton("❌ Close", callback_data="m_close")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"✅ Found {len(matches)} matches:"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    return REPO_MANAGE

# --- Management Menu ---
async def send_repo_management_menu(update, query, context):
    token = context.user_data['token']
    repo = context.user_data['active_repo']
    repo_name = repo.rsplit('/', 1)[-1]
    res = github_req("GET", f"/repos/{repo}", token).json()
    is_private = res.get('private')
    is_archived = res.get('archived')
    visibility_label = "🔓 Set to Public" if is_private else "🔒 Set to Private"
    archive_label = "📤 Unarchive repo" if is_archived else "📥 Archive repo"
    if 'now_page' in context.user_data:
        now_page = context.user_data['now_page']
    else:
        now_page = 1
    keyboard = [
        [InlineKeyboardButton("🖥️ Code", callback_data="m_codes"), InlineKeyboardButton("📝 New File", callback_data="m_newf")],
        [InlineKeyboardButton("✏️ Rename Repo", callback_data="m_rename"), InlineKeyboardButton(f"{visibility_label}", callback_data="m_toggle_vis")],
        [InlineKeyboardButton("🚀 Releases", callback_data="rel_list_view"), InlineKeyboardButton("✨ Create Release", callback_data="rel_create_start")],
        [InlineKeyboardButton(f"{archive_label}", callback_data="m_toggle_arch"), InlineKeyboardButton("⚠️ DELETE REPO", callback_data="m_delr")],
        [InlineKeyboardButton("⬅️ Back", callback_data="m_back_search" if 'search_repo' in context.user_data else f"page_{now_page}")],
        [InlineKeyboardButton("❌ Close", callback_data="m_close")]
    ]
    
    txt = (
        f"📝 *{repo_name}*\n\n"
        f"⭐ *Stars:* {res['stargazers_count']}\n"
        f"🍴 *Forks:* {res['forks_count']}\n"
        f"{'🔒 *Private*' if is_private else '🔓 *Public*'}\n"
        f"{'📦 *Archived*' if is_archived else '✅ *Active*'}\n\n"
        "🛠️ Select an option to manage:"
    )
    try:
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(keyboard),parse_mode='Markdown')
    except:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    return REPO_MANAGE

async def repo_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    repo = data.replace("sel_", "") if data.startswith("sel_") else data.replace("sea_", "")
    context.user_data['active_repo'] = repo

    return await send_repo_management_menu(update, query, context)

async def manager_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data

    if action == "m_close":
        await query.answer()
        await query.edit_message_text(
            "❌ Action closed.\n\n"
            "Available commands:\n"
            "/repositories - Browse and manage your repositories\n"
            "/search - Search repository with specific word\n"
            "/create - Create a new repository"
        )
        return ConversationHandler.END

    elif action == "ignore":
        await query.answer()
        return
    
    repo = context.user_data['active_repo']
    repo_name = repo.rsplit('/', 1)[-1]
    token = context.user_data['token']
    restricted_actions = ["m_newf", "m_rename", "f_edit", "f_ren", "f_del"]

    if action.startswith("page_"):
        await query.answer()
        new_page = int(action.split("_")[1])
        context.user_data['now_page'] = new_page
        all_repos = context.user_data.get('all_repos_cache', [])
        
        keyboard = get_repo_markup(all_repos, page=new_page)
        keyboard += [[InlineKeyboardButton("❌ Close", callback_data="m_close")]]
        await query.edit_message_text("📂 Select a repository:", reply_markup=InlineKeyboardMarkup(keyboard))
        return REPO_MANAGE

    if action in restricted_actions:
        res = github_req("GET", f"/repos/{repo}", token)
        if res.status_code == 200 and res.json().get('archived'):
            await query.answer(
                "⚠️ This repository is archived and read-only. Unarchive it first to make changes!", 
                show_alert=True
            )
            return REPO_MANAGE
            
    if action == "m_rename":
        await query.answer()
        context.user_data['user_state'] = RENAME_REPO
        await query.edit_message_text(f"✏️ Enter a new name for `{repo_name}`:\n\nOr /cancel ❌", parse_mode='Markdown')
        return RENAME_REPO
        
    elif action == "m_codes":
        await query.answer()
        return await codes(update, query, context)

    elif action == "m_toggle_vis":
        repo_data = github_req("GET", f"/repos/{repo}", token).json()
        current_status = repo_data.get('private')
        
        new_status = not current_status
        payload = {"private": new_status}
        
        res = github_req("PATCH", f"/repos/{repo}", token, payload)
        
        if res.status_code == 200:
            status_text = "Private" if new_status else "Public"
            await query.answer(f"✅ Repository is now {status_text}!", show_alert=True)
            return await send_repo_management_menu(update, query, context)
        else:
            await query.answer("❌ Failed to change visibility.", show_alert=True)

    elif action == "m_delr":
        await query.answer()
        kb = [[InlineKeyboardButton("✅ Confirm Delete", callback_data="conf_repo_yes"), InlineKeyboardButton("❌ Cancel", callback_data="conf_repo_no")]]
        await query.edit_message_text(f"⚠️ DELETE `{repo_name}` permanently?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return CONFIRM_ACTION

    elif action == "m_toggle_arch":
        repo_data = github_req("GET", f"/repos/{repo}", token).json()
        current_archived = repo_data.get('archived')
        new_status = not current_archived
        res = github_req("PATCH", f"/repos/{repo}", token, {"archived": new_status})
        
        if res.status_code == 200:
            action_text = "archived" if new_status else "unarchived"
            await query.answer(f"✅ Repository {action_text}!", show_alert=True)
            return await send_repo_management_menu(update, query, context)
        else:
            error_msg = res.json().get('message', 'Check your token permissions.')
            await query.answer(f"❌ Error: {error_msg}", show_alert=True)

    elif action == "m_newf":
        await query.answer()
        context.user_data['user_state'] = NEW_FILE_PATH
        await query.edit_message_text("🆕 Enter the path for the new file (e.g., `src/main.py`):\n\nOr /cancel ❌", parse_mode='Markdown')
        return NEW_FILE_PATH

    elif action == "f_edit":
            await query.answer()
            return await initiate_file_edit(query, context)

    elif action == "f_ren":
        await query.answer()
        context.user_data['user_state'] = RENAME_FILE_NEW_NAME
        await query.edit_message_text(f"✏️ Enter NEW name for `{context.user_data['active_file']['name']}`:\n\nOr /cancel ❌", parse_mode='Markdown')
        return RENAME_FILE_NEW_NAME

    elif action == "f_del":
        await query.answer()
        type = context.user_data['active_file']['type']
        path = context.user_data['active_file']['path']
        kb = [[InlineKeyboardButton("✅ Confirm Delete", callback_data="conf_file_yes"), InlineKeyboardButton("❌ Cancel", callback_data=f"view_{type}_{path}")]]
        await query.edit_message_text(f"⚠️ Delete `{path}` permanently?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return REPO_MANAGE
    
    elif action == "conf_file_yes":
        path = context.user_data['active_file']['path']
        f = github_req("GET", f"/repos/{repo}/contents/{path}", token).json()
        github_req("DELETE", f"/repos/{repo}/contents/{path}", token, {"message": "@GitHubClient_bot Delete", "sha": f['sha']})
        await query.edit_message_text("✅ File Deleted.")
        return await codes(update, query, context)
    
    elif action == "rel_list_view":
        await query.answer()
        return await show_releases_tags_dashboard(query, context, tab="releases")

    elif action.startswith("rel_tab_switch_"):
        await query.answer()
        target_tab = action.replace("rel_tab_switch_", "")
        return await show_releases_tags_dashboard(query, context, tab=target_tab)

    elif action.startswith("show_rel_"):
        await query.answer()
        rel_id = action.replace("show_rel_", "")
        return await show_release_details(update, query, context, rel_id)

    elif action.startswith("rel_edit_menu_"):
        await query.answer()
        return await show_release_edit_menu(update, query, context)

    elif action.startswith("rel_back_to_main"):
        await query.answer()
        return await send_repo_management_menu(update, query, context)

    elif action.startswith("rel_del_req_"):
        await query.answer()
        return await release_delete_request(query, context, action.replace("rel_del_req_", ""))

    elif action.startswith("rel_del_confirm_"):
        return await release_delete_execute(query, context, action.replace("rel_del_confirm_", ""))

    elif action.startswith("tag_del_req_"):
        await query.answer()
        return await tag_delete_request(query, context, action.replace("tag_del_req_", ""))

    elif action.startswith("tag_del_confirm_"):
        return await tag_delete_execute(query, context, action.replace("tag_del_confirm_", ""))

    elif action.startswith("rel_assets_"):
        await query.answer()
        return await show_release_assets(query, context, action.replace("rel_assets_", ""))

    elif action == "rel_edit_title":
        await query.answer()
        return await initiate_release_field_edit(query, context, "title")

    elif action == "rel_edit_desc":
        await query.answer()
        return await initiate_release_field_edit(query, context, "desc")
    
    elif action.startswith("lbl_set_"):
        await query.answer()
        choice = action.replace("lbl_set_", "")
        return await rel_create_execute(query, context, choice)

    elif action == "rel_edit_lbl_menu":
        await query.answer()
        return await show_edit_label_menu(query, context)

    elif action.startswith("edit_lbl_save_"):
        await query.answer()
        choice = action.replace("edit_lbl_save_", "")
        return await save_release_label_edit(update, query, context, choice)
    
    elif action == "rel_asset_add":
        await query.answer()
        return await initiate_asset_upload(query, context)

    elif action == "rel_asset_del_list":
        await query.answer()
        return await list_release_assets_for_deletion(query, context)

    elif action == "rel_edit_tag":
        await query.answer()
        return await show_tags_for_release_edit(update, query, context)

    elif action.startswith("as_del_req"):
        await query.answer()
        return await asset_delete_request(query, action.replace("as_del_req_", ""))
    
    elif action.startswith("as_del_conf_"):
        await query.answer()
        return await delete_asset_execute(query, context, action.replace("as_del_conf_", ""))

    elif action.startswith("save_tag_shift_"):
        await query.answer()
        return await save_release_tag_shift(update, query, context, action.replace("save_tag_shift_", ""))

    elif action == "cr_shift_tag_manual_prompt":
        await query.answer()
        return await tag_shift_manual_prompt(query, context)
    
    elif action.startswith("as_down_"):
        await query.answer()
        return await download_release_asset(update, context)
        
    elif action == "rel_create_start":
        await query.answer()
        return await rel_create_start(query, context)

    elif action == "cr_tag_manual_prompt":
        await query.answer()
        return await rel_create_tag_manual_prompt(query)
    
    elif action.startswith("cr_tag_"):
        await query.answer()
        return await rel_create_target_step(query, context, action.replace("cr_tag_", ""))

    elif action.startswith("cr_targ_"):
        await query.answer()
        return await rel_create_title_prompt(query, context, action.replace("cr_targ_", ""))
    
    elif action == "m_back_search":
        await query.answer()
        await search_process(update, context)

# --- Browse & Download Logic ---
async def codes(update, query, context):
    repo = context.user_data['active_repo']
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/contents/", token).json()
    kb = [[InlineKeyboardButton(f"{'📁' if i['type']=='dir' else '📄'} {i['name']}", callback_data=f"view_{i['type']}_{i['path']}")] for i in res]
    text = "📂 Contents:" if kb else "📭 No contents found."
    kb += [[InlineKeyboardButton("⬅️ Back", callback_data=f"sea_{repo}" if 'search_repo' in context.user_data else f"sel_{repo}"), InlineKeyboardButton("❌ Close", callback_data="m_close")]]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    except:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return REPO_MANAGE

async def view_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
    except:
        pass

    try:
        _, itype, ipath = query.data.split('_', 2)
        context.user_data['itype'], context.user_data['ipath'] = itype, ipath
    except:
        itype, ipath = context.user_data['itype'], context.user_data['ipath']
        
    repo, token = context.user_data['active_repo'], context.user_data['token']

    res = github_req("GET", f"/repos/{repo}/contents/{ipath}", token).json()
    if itype == 'dir':
        kb = [[InlineKeyboardButton(f"{'📁' if i['type']=='dir' else '📄'} {i['name']}", callback_data=f"view_{i['type']}_{i['path']}")] for i in res]
        kb += [[InlineKeyboardButton("⬅️ Back", callback_data=f"sel_{repo}"), InlineKeyboardButton("❌ Close", callback_data="m_close")]]
        try:
            await query.edit_message_text(f"📁 Folder: {ipath}", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text(f"📁 Folder: {ipath}", reply_markup=InlineKeyboardMarkup(kb))
        return REPO_MANAGE
    else:
        context.user_data['active_file'] = res
        name = res['name']
        path = res['path']
        if path == name:
            path = "Home"
        
        text = (f"📄 *File:* `{name}`\n"
                f"📍 *Path:* `{path}`\n"
                f"⚖️ *Size:* {format_size(int(res['size']))}")
        
        keyboard = [
            [InlineKeyboardButton("📥 Download", callback_data="do_wn"), InlineKeyboardButton("✏️ Edit", callback_data="f_edit")],
            [InlineKeyboardButton("🏷 Rename", callback_data="f_ren"), InlineKeyboardButton("🗑️ Delete", callback_data="f_del")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m_codes")],
            [InlineKeyboardButton("❌ Close", callback_data="m_close")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return REPO_MANAGE

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    f = context.user_data['active_file']
    res = requests.get(f['download_url'], headers={"Authorization": f"token {context.user_data['token']}"})
    await query.message.reply_document(document=io.BytesIO(res.content), filename=f['name'])

async def rename_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    data = {"name": new_name}
    res = github_req("PATCH", f"/repos/{repo}", token, data)
    
    if res.status_code == 200:
        await update.message.reply_text(f"✅ Repository renamed to `{new_name}` successfully!", parse_mode='Markdown')
        context.user_data['active_repo'] = repo.rsplit('/', 1)[0] + '/' + new_name
    else:
        error_msg = res.json().get('message', 'Unknown error')
        await update.message.reply_text(f"❌ Failed to rename: {error_msg}")
    return await send_repo_management_menu(update, update.callback_query, context)

# --- Update & Delete Logic ---
async def new_file_content_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_file_path'] = update.message.text
    await update.message.reply_text("📥 Now send the content as text message or file:\n\nYou can send the file as a regular media or document.\n❌ /cancel")
    return NEW_FILE_CONTENT

async def new_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo = context.user_data['active_repo']
    path = context.user_data['new_file_path']
    token = context.user_data['token']
    
    if update.message.text:
        content = update.message.text
    else:
        msg = update.message
        tg_file = None
        
        if msg.photo:
            tg_file = await context.bot.get_file(msg.photo[-1].file_id)
        elif msg.video:
            tg_file = await context.bot.get_file(msg.video.file_id)
        elif msg.audio:
            tg_file = await context.bot.get_file(msg.audio.file_id)
        elif msg.document:
           tg_file = await context.bot.get_file(msg.document.file_id)

        content = (await tg_file.download_as_bytearray()).decode('utf-8')

    data = {
        "message": f"Created {path} via @GitHubClient_bot",
        "content": base64.b64encode(content.encode()).decode()
    }
    
    res = github_req("PUT", f"/repos/{repo}/contents/{path}", token, data)
    if res.status_code == 201:
        await update.message.reply_text(f"✅ File `{path}` created!", parse_mode='Markdown')
        return await codes(update, update.callback_query, context)
    else:
        await update.message.reply_text(f"❌ Error: {res.json().get('message')}")
    
async def initiate_file_edit(query, context):
    context.user_data['user_state'] = EDIT_FILE_CONTENT
    repo = context.user_data.get('active_repo')
    file_path = context.user_data['active_file']['path']
    
    ext = file_path.split('.')[-1].lower() if '.' in file_path else ''
    media_extensions = ['png', 'jpg', 'jpeg', 'gif', 'mp4', 'mkv', 'mp3', 'wav', 'ogg']
    
    if ext in media_extensions:
        context.user_data['is_media'] = True
        await query.edit_message_text(
            f"🖼️ *Media File:* `{file_path}`\n\n"
            "Media formats cannot be read as raw text. Send a new file, photo, video, or audio message now to completely replace this asset on GitHub:\n\n❌ /cancel",
            parse_mode='Markdown'
        )
        return EDIT_FILE_CONTENT
    else:
        context.user_data['is_media'] = False
        token = context.user_data['token']
        res = github_req("GET", f"/repos/{repo}/contents/{file_path}", token)
        if res.status_code == 200:
            file_data = res.json()
            raw_content = base64.b64decode(file_data.get('content', '')).decode('utf-8')
            preview = raw_content[:1500] + "\n..." if len(raw_content) > 1500 else raw_content
            
            ext_preview_map = {
                "py": "python",
                "json": "json",
                "js": "javascript",
                "html": "html",
                "css": "css",
                "md": "markdown"
            }
            preview_format = ext_preview_map.get(ext, "text")

            await query.edit_message_text(
                f"📝 *Editing:* `{file_path}`\n\n*Current Preview:*\n```{preview_format}\n{preview}\n```\n\nSend the new content as text message or file. This will overwrite the existing file on GitHub.\n\nYou can send the file as a regular media or document.\n\n❌ /cancel",
                parse_mode='Markdown'
            )
            return EDIT_FILE_CONTENT
        else:
            await query.edit_message_text("❌ Error loading target file data.")
            return REPO_MANAGE      
                              
async def edit_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    file_path = context.user_data.get('active_file')['path']
    filename = file_path.split('/')[-1]
    is_media = context.user_data.get('is_media', False)
    
    res = github_req("GET", f"/repos/{repo}/contents/{file_path}", token)
    if res.status_code != 200:
        await update.message.reply_text("❌ Failed to fetch file tracking details from GitHub.")
        return ConversationHandler.END
    
    sha = res.json().get('sha')
    if update.message.text:
        text_bytes = update.message.text.encode('utf-8')
        encoded_content = base64.b64encode(text_bytes).decode('utf-8')
        commit_message = f"📝 Edit text file content: {filename}"
    else:    
        msg = update.message
        tg_file = None
        
        if msg.photo:
            tg_file = await context.bot.get_file(msg.photo[-1].file_id)
        elif msg.video:
            tg_file = await context.bot.get_file(msg.video.file_id)
        elif msg.audio:
            tg_file = await context.bot.get_file(msg.audio.file_id)
        elif msg.document:
           tg_file = await context.bot.get_file(msg.document.file_id)
        
        if not tg_file:
            await update.message.reply_text("❌ Please send a valid image, video, audio track, or document.")
            return EDIT_FILE_CONTENT

        file_bytes = await tg_file.download_as_bytearray()
        encoded_content = base64.b64encode(file_bytes).decode('utf-8')
        commit_message = f"🔄 Replace binary media asset: {filename}" if is_media else f"📝 Edit text file content: {filename}"

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "sha": sha
    }
    
    put_res = github_req("PUT", f"/repos/{repo}/contents/{file_path}", token, payload)
    
    if put_res.status_code == 200 or put_res.status_code == 201:
        await update.message.reply_text(f"✅ Successfully updated `{file_path}` on GitHub!", parse_mode='Markdown')
    else:
        error_info = put_res.json().get('message', 'Check your file paths.')
        await update.message.reply_text(f"❌ Commit rejected by remote server: {error_info}")
        
    return await view_item_callback(update, context)

async def rename_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text
    repo = context.user_data.get('active_repo')
    token = context.user_data.get('token')
    file_obj = context.user_data.get('active_file')
    
    if not file_obj:
        await update.message.reply_text("❌ Error: File context lost. Please browse to the file again.")
        return ConversationHandler.END

    old_name = file_obj['name']
    old_path = file_obj['path']
    new_path = old_path.rsplit('/', 1)[0] + '/' + new_name if '/' in old_path else new_name
    context.user_data['ipath'] = new_path

    put_data = {
        "message": f"Renamed {old_path} to {new_path} via @GitHubClient_bot",
        "content": file_obj['content']
    }
    
    res_create = github_req("PUT", f"/repos/{repo}/contents/{new_path}", token, put_data)
    
    if res_create.status_code in [200, 201]:
        del_data = {
            "message": f"Cleanup: Deleted {old_path} after rename", 
            "sha": file_obj['sha']
        }
        github_req("DELETE", f"/repos/{repo}/contents/{old_path}", token, del_data)
        
        await update.message.reply_text(f"✅ Successfully renamed:\n`{old_name}` ➡️ `{new_name}`", parse_mode='Markdown')
    else:
        error_msg = res_create.json().get('message', 'Unknown error')
        await update.message.reply_text(f"❌ Failed to rename: {error_msg}")
        
    return await view_item_callback(update, context)

async def show_releases_tags_dashboard(query, context, tab="releases"):
    repo = context.user_data.get('active_repo')
    repo_name = repo.rsplit('/', 1)[-1]
    token = context.user_data['token']
    context.user_data['rel_view_tab'] = tab

    rel_emoji = "🔹 " if tab == "releases" else ""
    tag_emoji = "🔹 " if tab == "tags" else ""
    
    nav_buttons = [
        InlineKeyboardButton(f"{rel_emoji}Releases", callback_data="rel_tab_switch_releases"),
        InlineKeyboardButton(f"{tag_emoji}Tags", callback_data="rel_tab_switch_tags")
    ]
    
    keyboard = [nav_buttons]
    text = f"🚀 *{repo_name}* \n\n"

    if tab == "releases":
        text += "📋 *Repository Releases:* \n"

        latest_id = None
        latest_res = github_req("GET", f"/repos/{repo}/releases/latest", token)
        if latest_res.status_code == 200:
            latest_id = latest_res.json().get('id')

        res = github_req("GET", f"/repos/{repo}/releases", token)
        if res.status_code == 200 and res.json():
            for r in res.json():
                if r['id'] == latest_id:
                    suffix = " (Latest)"
                elif r.get('prerelease'):
                    suffix = " (Pre-release)"
                else:
                    suffix = ""
                
                label = f"📦 {r['name'] or r['tag_name']}{suffix}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"show_rel_{r['id']}")])
        else:
            text += "ℹ️ No releases found."
            
    else:
        text += "🏷️ *Repository Tags:* \n"
        res = github_req("GET", f"/repos/{repo}/tags", token)
        if res.status_code == 200 and res.json():
            tags = res.json()
            for t in tags:
                keyboard.append([
                    InlineKeyboardButton(f"🏷️ {t['name']}", callback_data="ignore"),
                    InlineKeyboardButton("🗑️", callback_data=f"tag_del_req_{t['name']}")
                ])
        else:
            text += "ℹ️ No tags found."

    keyboard.append([
        InlineKeyboardButton("⬅️ Back to Menu", callback_data="rel_back_to_main"),
        InlineKeyboardButton("❌ Close", callback_data="m_close")
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

async def show_release_details(update, query, context, release_id):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/releases/{release_id}", token)
    if res.status_code != 200:
        await query.answer("❌ Failed to fetch release details.", show_alert=True)
        return RELEASE_MENU

    rel = res.json()
    context.user_data['active_release'] = rel
    context.user_data['active_release_id'] = release_id

    text = (
        f"🚀 *Release:* {rel.get('name') or 'No Title'}\n"
        f"🏷️ *Tag:* `{rel.get('tag_name')}`\n"
        f"🌳 *Target:* `{rel.get('target_commitish')}`\n"
        f"📝 *Description:* \n{rel.get('body') or '_No description provided._'}"
    )

    keyboard = [
        [
            InlineKeyboardButton("📥 Assets", callback_data=f"rel_assets_{release_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"rel_edit_menu_{release_id}")
        ],
        [InlineKeyboardButton("🗑️ Delete Release", callback_data=f"rel_del_req_{release_id}")],
        [
            InlineKeyboardButton("⬅️ Back to List", callback_data="rel_list_view"),
            InlineKeyboardButton("❌ Close", callback_data="m_close")
        ]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

async def show_release_edit_menu(update, query, context):
    context.user_data['new_repo'] = "NO"
    rel = context.user_data.get('active_release')
    
    text = f"⚙️ *Editing Release:* `{rel.get('name') or rel.get('tag_name')}`\nSelect what you want to edit:"

    keyboard = [
        [
            InlineKeyboardButton("🏷️ Tag", callback_data="rel_edit_tag"),
            InlineKeyboardButton("🔤 Title", callback_data="rel_edit_title"),
            InlineKeyboardButton("📝 Description", callback_data="rel_edit_desc")
        ],
        [InlineKeyboardButton("🏷️ Release Label", callback_data="rel_edit_lbl_menu")],
        [
            InlineKeyboardButton("➕ Add an Asset", callback_data="rel_asset_add"),
            InlineKeyboardButton("➖ Delete an Asset", callback_data="rel_asset_del_list")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Release", callback_data=f"show_rel_{rel['id']}"),
            InlineKeyboardButton("❌ Close", callback_data="m_close")
        ]
    ]

    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

# --- RELEASE DELETION LOGIC ---
async def release_delete_request(query, context, release_id):
    rel = context.user_data.get('active_release')
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Delete", callback_data=f"rel_del_confirm_{release_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"show_rel_{release_id}")
        ]
    ]
    await query.edit_message_text(
        f"⚠️ *Danger Zone*\nAre you sure you want to permanently delete release *{rel.get('name')}*?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RELEASE_MENU

async def release_delete_execute(query, context, release_id):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']

    res = github_req("DELETE", f"/repos/{repo}/releases/{release_id}", token)
    if res.status_code == 204:
        await query.answer("✅ Release deleted successfully!", show_alert=True)
        return await show_releases_tags_dashboard(query, context, tab="releases")
    else:
        await query.answer("❌ Could not delete release from GitHub.", show_alert=True)
        return RELEASE_MENU


# --- TAG DELETION LOGIC ---
async def tag_delete_request(query, context, tag_name):
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Delete", callback_data=f"tag_del_confirm_{tag_name}"),
            InlineKeyboardButton("❌ Cancel", callback_data="rel_tab_switch_tags")
        ]
    ]
    await query.edit_message_text(
        f"⚠️ *Danger Zone*\nAre you sure you want to delete git tag `{tag_name}` from remote history?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RELEASE_MENU

async def tag_delete_execute(query, context, tag_name):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']

    res = github_req("DELETE", f"/repos/{repo}/git/refs/tags/{tag_name}", token)
    if res.status_code == 204:
        await query.answer(f"✅ Tag {tag_name} deleted!", show_alert=True)
        return await show_releases_tags_dashboard(query, context, tab="tags")
    else:
        await query.answer("❌ Failed to delete tag. It might be protected.", show_alert=True)
        return RELEASE_MENU

async def show_release_assets(query, context, release_id):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/releases/{release_id}", token)
    if res.status_code != 200:
        await query.answer("❌ Failed to fetch asset listings.", show_alert=True)
        return RELEASE_MENU

    rel = res.json()
    assets = rel.get('assets', [])
    
    text = f"📦 *Assets for Release:* `{rel.get('name') or rel.get('tag_name')}`\nTotal Items: {len(assets)}"
    keyboard = []

    for a in assets:
        keyboard.append([
            InlineKeyboardButton(f"📄 {a['name']} ({format_size(a['size'])})", callback_data="ignore"),
            InlineKeyboardButton("🌐 Link", url=a['browser_download_url']),
            InlineKeyboardButton("📥 Get", callback_data=f"as_down_{a['id']}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Back to Release", callback_data=f"show_rel_{release_id}"),
        InlineKeyboardButton("❌ Close", callback_data="m_close")
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

async def download_release_asset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📥 Fetching asset from GitHub...")
    
    asset_id = query.data.replace("as_down_", "")
    repo = context.user_data.get('active_repo')
    repo_name = repo.rsplit('/', 1)[-1]
    token = context.user_data['token']

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/octet-stream"
    }
    
    res = requests.get(f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}", headers=headers, stream=True)
    
    if res.status_code == 200:
        content_disp = res.headers.get('content-disposition', '')
        filename = "file"
        if "filename=" in content_disp:
            filename = content_disp.split("filename=")[1].strip('"')

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=res.raw.read(),
            filename=filename,
            caption=f"✅ Asset loaded from `{repo_name}`", parse_mode='Markdown'
        )
    else:
        await query.message.reply_text("❌ Failed to stream asset down from GitHub servers.")

async def initiate_release_field_edit(query, context, field_type):
    context.user_data['edit_target_field'] = field_type
    
    field_name = "Title" if field_type == "title" else "Description (Body Markdown)"
    
    await query.edit_message_text(f"📝 Send the new *{field_name}* text for this release:", parse_mode='Markdown')
    return EDIT_TEXT_FIELD

async def save_release_field_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = update.message.text
    field_type = context.user_data.get('edit_target_field')
    rel_id = context.user_data.get('active_release_id')
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    query = update.callback_query

    payload = {}
    if field_type == "title":
        payload["name"] = new_text
    elif field_type == "desc":
        payload["body"] = new_text

    res = github_req("PATCH", f"/repos/{repo}/releases/{rel_id}", token, payload)
    
    if res.status_code == 200:
        context.user_data['active_release'] = res.json()
        await update.message.reply_text("✅ Release updated successfully!")
    else:
        await update.message.reply_text("❌ Failed to save structural modifications to remote GitHub reference.")
        
    return await show_release_edit_menu(update, query, context)

async def show_edit_label_menu(query, context):
    rel = context.user_data.get('active_release')
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']

    latest_id = None
    latest_res = github_req("GET", f"/repos/{repo}/releases/latest", token)
    if latest_res.status_code == 200:
        latest_id = latest_res.json().get('id')

    if rel.get('id') == latest_id:
        current = "Latest"
    elif rel.get('prerelease'):
        current = "Pre-release"
    else:
        current = "None (Standard)"

    text = f"🏷️ Select the new label state classification:"
    
    keyboard = [
        [InlineKeyboardButton("⚪ None (Standard)" + (" ✅" if current == "None (Standard)" else ""), callback_data="edit_lbl_save_none")],
        [InlineKeyboardButton("🟠 Pre-release" + (" ✅" if current == "Pre-release" else ""), callback_data="edit_lbl_save_pre")],
        [InlineKeyboardButton("🟢 Latest Release" + (" ✅" if current == "Latest" else ""), callback_data="edit_lbl_save_latest")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"rel_edit_menu_{rel['id']}"), InlineKeyboardButton("❌ Close", callback_data="m_close")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

async def save_release_label_edit(update, query, context, label_choice):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    rel_id = context.user_data.get('active_release_id')
    
    payload = {}
    if label_choice == "none":
        payload["prerelease"] = False
        payload["make_latest"] = "false"
    elif label_choice == "pre":
        payload["prerelease"] = True
        payload["make_latest"] = "false"
    elif label_choice == "latest":
        payload["prerelease"] = False
        payload["make_latest"] = "true"

    res = github_req("PATCH", f"/repos/{repo}/releases/{rel_id}", token, payload)
    if res.status_code == 200:
        context.user_data['active_release'] = res.json()
        await query.answer("✅ Release label modified cleanly!", show_alert=True)
    else:
        await query.answer("❌ Modification rejected by remote server context rules.", show_alert=True)
        
    return await show_release_edit_menu(update, query, context)

async def list_release_assets_for_deletion(query, context):
    rel = context.user_data.get('active_release')
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/releases/{rel['id']}", token)
    assets = res.json().get('assets', []) if res.status_code == 200 else []
    
    text = "🗑️ *Select an asset to delete permanently:*"
    keyboard = []
    
    for a in assets:
        keyboard.append([InlineKeyboardButton(f"{a['name']}", callback_data=f"as_del_req_{a['name']}*{a['id']}")])
        
    keyboard.append([InlineKeyboardButton("⬅️ Back to Edit Menu", callback_data=f"rel_edit_menu_{rel['id']}"), InlineKeyboardButton("❌ Close", callback_data="m_close")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return RELEASE_MENU

async def asset_delete_request(query, asset_info):
    asset_name, asset_id= asset_info.split("*")
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Delete", callback_data=f"as_del_conf_{asset_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"rel_asset_del_list")
        ]
    ]
    await query.edit_message_text(
        f"⚠️ *Danger Zone*\nAre you sure you want to permanently delete asset *{asset_name}* from this release?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RELEASE_MENU

async def delete_asset_execute(query, context, asset_id):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    rel_id = context.user_data.get('active_release_id')

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    res = requests.delete(f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}", headers=headers)
    
    if res.status_code == 204:
        await query.answer("✅ Asset successfully vaporized!", show_alert=True)
    else:
        await query.answer("❌ Failed to clear asset from GitHub references.", show_alert=True)
        
    return await list_release_assets_for_deletion(query, context)

async def initiate_asset_upload(query, context):
    await query.edit_message_text("📥 *Send the file* you want to attach as a Release Asset:", parse_mode='Markdown')
    return CREATE_REL_ASSETS

async def upload_asset_to_github(repo, release_id, token, file_bytes, filename):
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/octet-stream",
        "Accept": "application/vnd.github+json"
    }
    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={filename}"
    return requests.post(url, headers=headers, data=file_bytes)

async def show_tags_for_release_edit(update, query, context):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    rel = context.user_data.get('active_release')
    
    res = github_req("GET", f"/repos/{repo}/tags", token)
    keyboard = []
    
    if res.status_code == 200:
        for t in res.json():
            is_active = t['name'] == rel.get('tag_name')
            label = f"🔹 {t['name']} (Active)" if is_active else t['name']
            keyboard.append([InlineKeyboardButton(label, callback_data=f"save_tag_shift_{t['name']}")])
        keyboard.append([InlineKeyboardButton("✍️ Type a New Tag", callback_data="cr_shift_tag_manual_prompt")])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"rel_edit_menu_{rel['id']}")])
    txt = "🏷️ *Select a new target tag reference for this release:*"
    markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(txt, reply_markup=markup, parse_mode='Markdown')
    except:
        await update.message.reply_text(txt, reply_markup=markup, parse_mode='Markdown')
    return RELEASE_MENU

async def tag_shift_manual_prompt(query, context):
    context.user_data['user_state'] = SAVE_TAG_SHIFT_MANUAL
    await query.edit_message_text("✍️ Send the name of the new tag you want to shift to (e.g., `v1.0.0`):\n\n❌ Cancel", parse_mode='Markdown')
    return SAVE_TAG_SHIFT_MANUAL

async def tag_shift_manual_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_tag = update.message.text.strip()
    return await save_release_tag_shift(update, update.callback_query, context, new_tag)

async def save_release_tag_shift(update, query, context, new_tag):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    rel_id = context.user_data.get('active_release_id')
    
    res = github_req("PATCH", f"/repos/{repo}/releases/{rel_id}", token, {"tag_name": new_tag})
    print(res.status_code, res.text)
    if res.status_code == 202 or res.status_code == 200:
        try:
            await query.answer(f"✅ Shifted release destination cleanly to tag: {new_tag}", show_alert=True)
        except:
            await update.message.reply_text(f"✅ Shifted release destination cleanly to tag: {new_tag}")
    else:
        try:
            await query.answer("❌ Refused by GitHub. Check tag constraints.", show_alert=True)
        except:
            await update.message.reply_text("❌ Refused by GitHub. Check tag constraints.")
    return await show_release_details(update, query, context, rel_id)

async def rel_create_start(query, context):
    context.user_data['new_repo'] = "YES"
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    context.user_data['new_rel_payload'] = {}
    
    res = github_req("GET", f"/repos/{repo}/tags", token)
    keyboard = []
    if res.status_code == 200 and res.json():
        for t in res.json():
            keyboard.append([InlineKeyboardButton(f"🏷️ {t['name']}", callback_data=f"cr_tag_{t['name']}")])
    
    keyboard.append([InlineKeyboardButton("✍️ Type a New Tag", callback_data="cr_tag_manual_prompt")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="rel_back_to_main")])
    
    await query.edit_message_text("🚀 *Create Release [1/6]*\nSelect a tag version baseline:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CREATE_REL_TAG

async def rel_create_tag_manual_prompt(query):
    await query.edit_message_text("✍️ Send the name of the new tag you want to create (e.g., `v1.0.0`):\n\n❌ Cancel", parse_mode='Markdown')
    return CREATE_REL_TAG_MANUAL

async def rel_create_tag_manual_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_typed_tag = update.message.text.strip()
    context.user_data['new_rel_payload']['tag_name'] = user_typed_tag
    
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/branches", token)
    keyboard = []
    if res.status_code == 200:
        for b in res.json():
            keyboard.append([InlineKeyboardButton(f"🌿 {b['name']}", callback_data=f"cr_targ_{b['name']}")] )
            
    await update.message.reply_text(
        f"✅ Tag set to `{user_typed_tag}`.\n\n🚀 *Create Release [2/6]*\nSelect target baseline branch:", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )
    return CREATE_REL_TARGET

async def rel_create_target_step(query, context, selected_tag):
    context.user_data['new_rel_payload']['tag_name'] = selected_tag
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    
    res = github_req("GET", f"/repos/{repo}/branches", token)
    keyboard = []
    if res.status_code == 200:
        for b in res.json():
            keyboard.append([InlineKeyboardButton(f"🌿 {b['name']}", callback_data=f"cr_targ_{b['name']}")])
            
    await query.edit_message_text("🚀 *Create Release [2/6]*\nSelect target baseline branch commit track:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CREATE_REL_TARGET

async def rel_create_title_prompt(query, context, selected_target):
    context.user_data['new_rel_payload']['target_commitish'] = selected_target
    await query.edit_message_text("🚀 *Create Release [3/6]*\nType out and send your **Release Title / Headline Label**:", parse_mode='Markdown')
    return CREATE_REL_TITLE

async def rel_create_desc_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_rel_payload']['name'] = update.message.text
    await update.message.reply_text("🚀 *Create Release [4/6]*\nType out and send your **Release Notes / Body Description Changelog**:", parse_mode='Markdown')
    return CREATE_REL_DESC

async def rel_create_label_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_rel_payload']['body'] = update.message.text
    
    # Present the label options as buttons
    keyboard = [
        [InlineKeyboardButton("⚪ None (Standard)", callback_data="lbl_set_none")],
        [InlineKeyboardButton("🟠 Pre-release", callback_data="lbl_set_pre")],
        [InlineKeyboardButton("🟢 Latest Release", callback_data="lbl_set_latest")]
    ]
    
    await update.message.reply_text(
        "🚀 *Create Release [5/6]*\nSelect a Release Label classification:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CREATE_REL_LABEL

async def rel_create_execute(query, context, label_choice):
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    payload = context.user_data['new_rel_payload']
    
    # Inject API parameters based on your structural rules
    if label_choice == "none":
        payload["prerelease"] = False
        payload["make_latest"] = "false"
    elif label_choice == "pre":
        payload["prerelease"] = True
        payload["make_latest"] = "false"
    elif label_choice == "latest":
        payload["prerelease"] = False
        payload["make_latest"] = "true"

    res = github_req("POST", f"/repos/{repo}/releases", token, payload)
    if res.status_code == 201:
        created_rel = res.json()
        context.user_data['active_release_id'] = created_rel['id']
        
        kb = [
            [InlineKeyboardButton("➕ Attach an Asset", callback_data="rel_asset_add")],
            [InlineKeyboardButton("🏁 Finish Setup", callback_data="rel_list_view")]
        ]
        await query.edit_message_text(
            "✅ *Release Base Draft Saved!* [6/6]\nDo you want to upload binary assets to this release now?", 
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode='Markdown'
        )
        return RELEASE_MENU
    else:
        await query.edit_message_text(f"❌ Creation rejected: {res.json().get('message', 'Unknown error')}")
        return ConversationHandler.END
    
async def process_incoming_file_asset_uploads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("❌ Please send a valid file asset document.")
        return CREATE_REL_ASSETS
        
    doc = update.message.document
    repo = context.user_data.get('active_repo')
    token = context.user_data['token']
    release_id = context.user_data.get('active_release_id')
    
    tg_file = await context.bot.get_file(doc.file_id)
    file_bytes = await tg_file.download_as_bytearray()
    
    res = await upload_asset_to_github(repo, release_id, token, file_bytes, doc.file_name)
    
    if res.status_code == 201:
        kb = [
            [InlineKeyboardButton("➕ Add Another", callback_data="rel_asset_add")],
            [InlineKeyboardButton("🏁 Done", callback_data="rel_edit_menu_" if context.user_data['new_repo'] == "NO" else "rel_list_view")]
        ]
        await update.message.reply_text(f"✅ Loaded `{doc.file_name}` as an asset!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Upload failed. Ensure the filename doesn't conflict.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="rel_asset_add")]]))
    return RELEASE_MENU


async def confirm_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "conf_pat_yes":
        context.user_data.clear()
        await query.edit_message_text(
            "🔒 *Logged out successfully.*\nYour PAT has been cleared from the bot's memory.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    elif query.data == "conf_pat_no":
        await query.edit_message_text("🚫 Logout cancelled by you.")
        return ConversationHandler.END
        
    token = context.user_data['token']
    repo = context.user_data['active_repo']

    if query.data == "conf_repo_yes":
        github_req("DELETE", f"/repos/{repo}", token)
        await query.edit_message_text("✅ Repository Deleted.")
        if "search_repo" in context.user_data:
            return await search_process(update, context)
        else:
            return await repositories(update, context)

    elif query.data == "conf_repo_no":
        return await send_repo_management_menu(update, query, context)
    else:
        await query.edit_message_text(
            "❌ Cancelled.\n\n"
            "Available commands:\n"
            "/repositories - Browse and manage your repositories\n"
            "/search - Search repository with specific word\n"
            "/create - Create a new repository"
        )
        return ConversationHandler.END

# --- Create Repo ---
async def create_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Name for new repo:\n\nOr /cancel ❌")
    return CREATE_NAME

async def create_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    github_req("POST", "/user/repos", context.user_data['token'], {"name": update.message.text})
    await update.message.reply_text("✅ Repository Created.")
    return await repositories(update, context)

def main():
    filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start), 
            CommandHandler('login', login_cmd),
            CommandHandler('logout', logout_start),
            CommandHandler('repositories', repositories), 
            CommandHandler('search', search_cmd),
            CommandHandler('create', create_cmd)
        ],
        states={
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_process)],
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_finish)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_process)],
            
            REPO_MANAGE: [
                CallbackQueryHandler(repo_select_callback, pattern="^(sel_|sea_)"),
                CallbackQueryHandler(manager_actions, pattern="^(m_|f_|page_|rel|conf|ignore)"),
                CallbackQueryHandler(view_item_callback, pattern="^view_"),
                CallbackQueryHandler(download_file, pattern="^do_wn")
            ],

            RELEASE_MENU: [
                CallbackQueryHandler(manager_actions, pattern="^(rel_|show_rel_|edit_lbl_|tag_|cr_|as_|save_|ignore|m_close)")
            ],
            NEW_FILE_PATH: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_file_content_step)],
            NEW_FILE_CONTENT: [MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.Document.ALL) & ~filters.COMMAND, new_file_finish)],
            
            EDIT_FILE_CONTENT: [MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.Document.ALL) & ~filters.COMMAND, edit_file_finish)],
            RENAME_REPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_finish)],
            RENAME_FILE_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_file_finish)],
            EDIT_TEXT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_release_field_edit)],
            SAVE_TAG_SHIFT_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, tag_shift_manual_save)],
            CREATE_REL_TAG_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, rel_create_tag_manual_save)],
            CREATE_REL_TAG: [CallbackQueryHandler(manager_actions, pattern="^(cr_tag_|rel)")],
            CREATE_REL_TARGET: [CallbackQueryHandler(manager_actions, pattern="^cr_targ_")],
            CREATE_REL_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rel_create_desc_prompt)],
            CREATE_REL_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, rel_create_label_prompt)],
            CREATE_REL_LABEL: [CallbackQueryHandler(manager_actions, pattern="^lbl_set_")],
            CREATE_REL_ASSETS: [MessageHandler(filters.Document.ALL & ~filters.COMMAND, process_incoming_file_asset_uploads)],
            CONFIRM_ACTION: [CallbackQueryHandler(confirm_action_handler, pattern="^conf_")]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )    
    app.add_handler(conv)
    app.run_polling()
    
if __name__ == '__main__':
    main()
