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

TOKEN = "8556710977:AAH4LasjgfKTpFPgeAG2bM2tqqo7pDGwliQ"
# States
LOGIN, CREATE_NAME, SEARCH_QUERY, REPO_MANAGE, RENAME_REPO, NEW_FILE_PATH, NEW_FILE_CONTENT, EDIT_FILE_CONTENT, RENAME_FILE_NEW_NAME, CONFIRM_ACTION = range(10)

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

    keyboard = [[InlineKeyboardButton(r['full_name'], callback_data=f"sel_{r['full_name']}")] for r in current_batch]
    
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
    await update.message.reply_text(
        "❌ Action cancelled.\n\n"
        "Commands:\n"
        "/repositories - Browse and manage your repositories\n"
        "/search - Search repository with specific word\n"
        "/create_repo - Create a new repository"
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
    await update.message.reply_text("🔍 Enter repo name keyword:")
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
async def send_repo_management_menu(query, context, repo):
    token = context.user_data['token']
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
        [InlineKeyboardButton(f"{archive_label}", callback_data="m_toggle_arch"), InlineKeyboardButton("⚠️ DELETE REPO", callback_data="m_delr")],
        [InlineKeyboardButton("⬅️ Back", callback_data="m_back_search" if 'search_repo' in context.user_data else f"page_{now_page}")],
        [InlineKeyboardButton("❌ Close", callback_data="m_close")]
    ]
    
    await query.edit_message_text(
        f"📝 *{repo}*\n\n"
        f"⭐ *Stars:* {res['stargazers_count']}\n"
        f"🍴 *Forks:* {res['forks_count']}\n"
        f"{'🔒 *Private*' if is_private else '🔓 *Public*'}\n"
        f"{'📦 *Archived*' if is_archived else '✅ *Active*'}\n\n"
        "🛠️ Select an option to manage:", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )
    return REPO_MANAGE

async def repo_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    repo = data.replace("sel_", "") if data.startswith("sel_") else data.replace("sea_", "")
    context.user_data['active_repo'] = repo
    
    return await send_repo_management_menu(query, context, repo)

async def manager_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    
    if action.startswith("page_"):
        await query.answer()
        new_page = int(action.split("_")[1])
        context.user_data['now_page'] = new_page
        all_repos = context.user_data.get('all_repos_cache', [])
        
        keyboard = get_repo_markup(all_repos, page=new_page)
        keyboard += [[InlineKeyboardButton("❌ Close", callback_data="m_close")]]
        await query.edit_message_text("📂 Select a repository:", reply_markup=InlineKeyboardMarkup(keyboard))
        return REPO_MANAGE

    elif action == "m_close":
        await query.answer()
        await query.edit_message_text(
            "❌ Action closed.\n\n"
            "Available commands:\n"
            "/repositories - Browse and manage your repositories\n"
            "/search - Search repository with specific word\n"
            "/create_repo - Create a new repository"
        )
        return ConversationHandler.END
    
    elif action == "ignore":
        await query.answer()
        return

    repo = context.user_data['active_repo']
    token = context.user_data['token']
    restricted_actions = ["m_newf", "m_rename", "f_edit", "f_ren", "f_del"]

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
        await query.edit_message_text(f"✏️ Enter a new name for `{repo}`:", parse_mode='Markdown')
        return RENAME_REPO
        
    elif action == "m_codes":
        await query.answer()
        res = github_req("GET", f"/repos/{repo}/contents/", token).json()
        kb = [[InlineKeyboardButton(f"{'📁' if i['type']=='dir' else '📄'} {i['name']}", callback_data=f"view_{i['type']}_{i['path']}")] for i in res]
        text = "📂 Contents:" if kb else "📭 No contents found."
        kb += [[InlineKeyboardButton("⬅️ Back", callback_data=f"sea_{repo}" if 'search_repo' in context.user_data else f"sel_{repo}"), InlineKeyboardButton("❌ Close", callback_data="m_close")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return REPO_MANAGE

    elif action == "m_toggle_vis":
        repo = context.user_data['active_repo']
        token = context.user_data['token']
        
        repo_data = github_req("GET", f"/repos/{repo}", token).json()
        current_status = repo_data.get('private')
        
        new_status = not current_status
        payload = {"private": new_status}
        
        res = github_req("PATCH", f"/repos/{repo}", token, payload)
        
        if res.status_code == 200:
            status_text = "Private" if new_status else "Public"
            await query.answer(f"✅ Repository is now {status_text}!", show_alert=True)
            return await send_repo_management_menu(query, context, repo)
        else:
            await query.answer("❌ Failed to change visibility.", show_alert=True)

    elif action == "m_delr":
        await query.answer()
        kb = [[InlineKeyboardButton("✅ Confirm Delete", callback_data="conf_repo_yes"), InlineKeyboardButton("❌ Cancel", callback_data="conf_no")]]
        await query.edit_message_text(f"⚠️ DELETE `{repo}` permanently?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return CONFIRM_ACTION

    elif action == "m_toggle_arch":
        repo_data = github_req("GET", f"/repos/{repo}", token).json()
        current_archived = repo_data.get('archived')
        new_status = not current_archived
        res = github_req("PATCH", f"/repos/{repo}", token, {"archived": new_status})
        
        if res.status_code == 200:
            action_text = "archived" if new_status else "unarchived"
            await query.answer(f"✅ Repository {action_text}!")
            return await send_repo_management_menu(query, context, repo)
        else:
            error_msg = res.json().get('message', 'Check your token permissions.')
            await query.answer(f"❌ Error: {error_msg}", show_alert=True)

    elif action == "m_newf":
        await query.answer()
        await query.edit_message_text("🆕 Enter the path for the new file (e.g., `src/main.py`):", parse_mode='Markdown')
        return NEW_FILE_PATH

    elif action == "f_edit":
        await query.answer()
        await query.edit_message_text(f"📝 Send new content for `{context.user_data['active_file']['name']}` (Text or File):", parse_mode='Markdown')
        return EDIT_FILE_CONTENT

    elif action == "f_ren":
        await query.answer()
        await query.edit_message_text(f"✏️ Enter NEW path/name for `{context.user_data['active_file']['name']}`:", parse_mode='Markdown')
        return RENAME_FILE_NEW_NAME

    elif action == "f_del":
        await query.answer()
        path = context.user_data['active_file']['path']
        kb = [[InlineKeyboardButton("✅ Confirm Delete", callback_data="conf_file_yes"), InlineKeyboardButton("❌ Cancel", callback_data="conf_no")]]
        await query.edit_message_text(f"⚠️ Delete `{path}` permanently?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return CONFIRM_ACTION

    elif action == "m_back_search":
        await query.answer()
        await search_process(update, context)

# --- Browse & Download Logic ---
async def view_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
        await query.edit_message_text(f"📁 Folder: {ipath}", reply_markup=InlineKeyboardMarkup(kb))
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
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
    else:
        error_msg = res.json().get('message', 'Unknown error')
        await update.message.reply_text(f"❌ Failed to rename: {error_msg}")
        
    return ConversationHandler.END

# --- Update & Delete Logic ---
async def new_file_content_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_file_path'] = update.message.text
    await update.message.reply_text("📥 Now send the content (Text or File):")
    return NEW_FILE_CONTENT

async def new_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo = context.user_data['active_repo']
    path = context.user_data['new_file_path']
    token = context.user_data['token']
    
    if update.message.document:
        f = await context.bot.get_file(update.message.document.file_id)
        content = (await f.download_as_bytearray()).decode('utf-8')
    else:
        content = update.message.text

    data = {
        "message": f"Created {path} via @GitHubClient_bot",
        "content": base64.b64encode(content.encode()).decode()
    }
    
    res = github_req("PUT", f"/repos/{repo}/contents/{path}", token, data)
    if res.status_code == 201:
        await update.message.reply_text(f"✅ File `{path}` created!", parse_mode='Markdown')
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"❌ Error: {res.json().get('message')}")
    

async def edit_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_obj = context.user_data['active_file']
    repo = context.user_data['active_repo']
    token = context.user_data['token']

    if update.message.document:
        f = await context.bot.get_file(update.message.document.file_id)
        content = (await f.download_as_bytearray()).decode('utf-8')
    else:
        content = update.message.text

    data = {
        "message": f"Edited {file_obj['name']} via @GitHubClient_bot",
        "content": base64.b64encode(content.encode()).decode(),
        "sha": file_obj['sha']
    }
    
    github_req("PUT", f"/repos/{repo}/contents/{file_obj['path']}", token, data)
    await update.message.reply_text(f"✅ `{file_obj['name']}` updated!", parse_mode='Markdown')
    return ConversationHandler.END

async def rename_file_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_path = update.message.text
    repo = context.user_data.get('active_repo')
    token = context.user_data.get('token')
    
    file_obj = context.user_data.get('active_file')
    
    if not file_obj:
        await update.message.reply_text("❌ Error: File context lost. Please browse to the file again.")
        return ConversationHandler.END

    old_path = file_obj['path']

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
        
        await update.message.reply_text(f"✅ Successfully renamed:\n`{old_path}` ➡️ `{new_path}`", parse_mode='Markdown')
    else:
        error_msg = res_create.json().get('message', 'Unknown error')
        await update.message.reply_text(f"❌ Failed to rename: {error_msg}")
        
    return ConversationHandler.END

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
    elif query.data == "conf_file_yes":
        path = context.user_data['active_file']['path']
        f = github_req("GET", f"/repos/{repo}/contents/{path}", token).json()
        github_req("DELETE", f"/repos/{repo}/contents/{path}", token, {"message": "@GitHubClient_bot Delete", "sha": f['sha']})
        await query.edit_message_text("✅ File Deleted.")
    else:
        await query.edit_message_text(
            "❌ Cancelled.\n\n"
            "Available commands:\n"
            "/repositories - Browse and manage your repositories\n"
            "/search - Search repository with specific word\n"
            "/create_repo - Create a new repository"
        )
    return ConversationHandler.END

# --- Create Repo ---
async def create_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Name for new repo:")
    return CREATE_NAME

async def create_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    github_req("POST", "/user/repos", context.user_data['token'], {"name": update.message.text})
    await update.message.reply_text("✅ Repository Created.")
    return ConversationHandler.END

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
            CommandHandler('create_repo', create_cmd)
        ],
        states={
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_process)],
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_finish)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_process)],
            
            REPO_MANAGE: [
                CallbackQueryHandler(repo_select_callback, pattern="^(sel_|sea_)"),
                CallbackQueryHandler(manager_actions, pattern="^(m_|f_|page_|ignore)"),
                CallbackQueryHandler(view_item_callback, pattern="^view_"),
                CallbackQueryHandler(download_file, pattern="^do_wn")
            ],
            
            NEW_FILE_PATH: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_file_content_step)],
            NEW_FILE_CONTENT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, new_file_finish)],
            
            EDIT_FILE_CONTENT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, edit_file_finish)],
            RENAME_REPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_finish)],
            RENAME_FILE_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_file_finish)],
            
            CONFIRM_ACTION: [CallbackQueryHandler(confirm_action_handler, pattern="^conf_")],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )    
    app.add_handler(conv)
    app.run_polling()
    
if __name__ == '__main__':
    main()