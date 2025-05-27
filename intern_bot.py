from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, ConversationHandler, filters
import logging
from datetime import datetime, timedelta,date
import uuid
from decimal import Decimal

from webserver import run_web_server
import threading
from db_utils import get_registered_interns, get_intern_by_telegram, update_leave_balance, save_leave_application, update_leave_taken, cancel_leave_application, get_approved_leaves,delete_user

from dotenv import load_dotenv
import os

import uuid
import time
from datetime import datetime


# Load environment variables from .env file
load_dotenv()


# --------------------------------------
# Section 1: Setup
# --------------------------------------

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Get registered interns from the database for verification purposes
registered_interns = get_registered_interns()
print(f"Loaded {len(registered_interns)} registered interns")
print(registered_interns)

# Initialize the bot with your token (put in env file in the future)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# State constants for conversation handler
LEAVE_TYPE, DAY_PORTION, START_DATE, END_DATE, CONFIRMATION = range(5)  # Reordered states
CHOOSE_LEAVE_TO_CANCEL, CONFIRM_CANCEL = range(5, 7) 
DOCUMENT_SUBMISSION = "document_submission"

# Leave types
leave_types = ["Annual Leave", "Medical Leave", "No Pay Leave", "Compassionate Leave", "Off in Lieu"]  


# Function to ensure username is always available
def ensure_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Make sure username is in context.user_data, add it if not"""
    if "username" not in context.user_data:
        user = update.effective_user
        username = user.username
        if username not in registered_interns:
            return None
        context.user_data["username"] = username
    return context.user_data["username"]

# Function to generate main menu buttons
def main_menu():
    keyboard = [
        [InlineKeyboardButton("Check Leave Balance", callback_data="balance")],
        [InlineKeyboardButton("Apply for Leave", callback_data="apply_leave")],
        [InlineKeyboardButton("Cancel Leave", callback_data="cancel_leave")],
        [InlineKeyboardButton("Submit Documents", url=os.getenv("FORM_URL"))]
    ]
    return InlineKeyboardMarkup(keyboard)

# Function to generate a back button
def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back")]])

# --------------------------------------
# Section 2: Start Command and Button Handlers
# --------------------------------------

# Command: /start. 
# This function is called when the user starts the bot or sends the /start command.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    username = user.username  # Get Telegram username
    global intern_info
    intern_info = get_intern_by_telegram(username)
    date_today = date.today()

    # lgoin checks
    """Unregistered interns check"""
    if username not in registered_interns:
        await update.message.reply_text("You are not registered in the system. Please contact HR.")
        return

        # Check if today is before internship start date or after end date
    elif date_today < intern_info["start_date"]:
        await update.message.reply_text("Your internship has not started yet. Please contact HR.")
        return
    elif date_today > intern_info["end_date"]:
        await update.message.reply_text("Your internship has ended. Please contact HR.")
        return

        
    # Store username in context.user_data
    context.user_data["username"] = username  

    """Welcome message with buttons"""
    await update.message.reply_text(f"Hello, @{username}!")
    await update.message.reply_text("Welcome to the Leave Management System! Here you can check your leave balance, apply for leave and update your leaves")
    await update.message.reply_text("You can start using your leaves right from the first day of your internship. Feel free to plan your leaves whenever you want.")
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())

# Function to handle general button clicks outside of conversations
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks"""
    query = update.callback_query
    await query.answer()
    
    # Ensure username is available
    ensure_username(update, context)
    
    if query.data == "balance":
        await balance(update, context, query)
    elif query.data == "cancel_leave":
        await cancel_leave_start(update, context, query)  # Add this line
    elif query.data == "back":
        if query.message.text != "Welcome! Choose an option:":
            await query.edit_message_text("Welcome! Choose an option:", reply_markup=main_menu())

# --------------------------------------
# Section 3: Check Leave Balance
# --------------------------------------

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> None:
    # Ensure username is available
    username = ensure_username(update, context)
    if not username:
        message = "You are not registered in the system. Please contact HR."
        if query:
            await query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    # Fetch intern leave balances and approved leaves
    intern_info = get_intern_by_telegram(username)
    approved_leaves = get_approved_leaves(username)
    
    # Retrieve the current leave balance
    al_balance = intern_info["al_balance"]
    mc_balance = intern_info["mc_balance"]
    # compassionate_balance = intern_info["compassionate_balance"] --> compassionate leave is by default 3 
    oil_balance = intern_info["oil_balance"]
    
    # Create the balance message to show leave balances
    message = f"📊 *YOUR LEAVE BALANCE*\n\n"
    message += f"Annual Leave: *{al_balance}* day(s)\n"
    message += f"Medical Leave: *{mc_balance}* day(s)\n"
    message += f"Off in Lieu: *{oil_balance}* day(s)\n\n"
    
    # Show upcoming approved leaves
    message += "👍❤ *UPCOMING APPROVED LEAVES*\n\n"
    
    if not approved_leaves:
        message += "You have no approved upcoming leaves."
    else:
        for leave in approved_leaves:
            start_date = leave['start_date'].strftime("%d %b %Y")
            end_date = leave['end_date'].strftime("%d %b %Y") if leave['end_date'] != leave['start_date'] else None
            
            if end_date:
                date_str = f"{start_date} to {end_date}"
            else:
                date_str = start_date
                
            portion_str = f" {leave['day_portion']}" if leave['day_portion'] not in ['Full Day', None] else ""
            
            message += f"• *{leave['leave_type']}*: {date_str},{portion_str} - Duration: {leave['leave_duration']} day(s)\n"
            

    # Create keyboard with back button
    keyboard = [[InlineKeyboardButton("Back to Main Menu", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.message:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# --------------------------------------
# Section 4: Apply Leave
# --------------------------------------

# Entry point for leave application
async def apply_leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Choose leave type - This is the entry point triggered by command or callback"""
    # Ensure username is available
    username = ensure_username(update, context)
    intern_info= get_intern_by_telegram(username)
    
    if not username:
        if update.callback_query:
            await update.callback_query.message.reply_text("You are not registered in the system. Please contact HR.")
        else:
            await update.message.reply_text("You are not registered in the system. Please contact HR.")
        return ConversationHandler.END
    
    # list out leave types to choose from
    keyboard = [[lt] for lt in leave_types]
    keyboard.append(["Cancel"])  
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text("Please choose the type of leave you want to apply for:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please choose the type of leave you want to apply for:", reply_markup=reply_markup)
    
    return LEAVE_TYPE

async def leave_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: Ask for leave duration type (full day or half day)"""
    
    # Get reply from previous step
    user_input = update.message.text

    # Error handling for invalid leave type
    if user_input not in leave_types and user_input != "Cancel":
        await update.message.reply_text("Invalid leave type. Please choose a valid leave type.")
        return LEAVE_TYPE
    
    # Check if user wants to cancel
    if user_input == "Cancel":
        return await cancel(update, context)
    
    # Store the selected leave type in user_data
    context.user_data["leave_type"] = user_input
    
    # Check if user selected Medical or Compassionate Leave to facilitate document submission
    if user_input in ["Medical Leave", "Compassionate Leave"]:
        # Create inline keyboard with document submission link and options
        inline_keyboard = [
            [InlineKeyboardButton("Submit Documents", url=os.getenv("FORM_URL"))],
            [InlineKeyboardButton("I have submitted documents - Proceed", callback_data="documents_submitted")],
            [InlineKeyboardButton("Cancel Application", callback_data="cancel_application")]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        
        document_type = "medical certificate" if user_input == "Medical Leave" else "supporting documents"
        message_text = (
            f"For {user_input}, you need to submit {document_type}.\n\n"
            f"Please use the button below to submit your documents, then click 'Proceed' to continue with your application."
        )
        
        await update.message.reply_text(message_text, reply_markup=reply_markup)
        return DOCUMENT_SUBMISSION
    
    # For other leave types, proceed directly to day portion selection
    keyboard = [["Full Day", "Half Day (AM)", "Half Day (PM)"], ["Cancel"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text("Please select leave duration type:", reply_markup=reply_markup)
    return DAY_PORTION

# Process the document submission callback
async def document_submission_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle document submission callback"""
    query = update.callback_query
    await query.answer()
    
    username = ensure_username(update, context)
    
    # If user has submitted documents proceed with leave application
    if query.data == "documents_submitted":
        # User has submitted documents, proceed with leave application
        keyboard = [["Full Day", "Half Day (AM)", "Half Day (PM)"], ["Cancel"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await query.edit_message_text("Great! Now please select leave duration type:")
        await query.message.reply_text("Please select leave duration type:", reply_markup=reply_markup)
        return DAY_PORTION
        
    elif query.data == "cancel_application":
        # User wants to cancel the application
        await query.edit_message_text("Leave application cancelled.")
        
        # Return to main menu
        await query.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
        return ConversationHandler.END
    
    return DOCUMENT_SUBMISSION

async def day_portion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: Based on the day portion, ask for start date"""
    # Ensure username is available
    ensure_username(update, context)

    # Get reply from previous step
    user_input = update.message.text
    
    # Check if user wants to cancel
    if user_input == "Cancel":
        return await cancel(update, context)
    
    # Save user input for day portion
    context.user_data["day_portion"] = user_input
    
    # Store if this is a half day leave
    is_half_day = user_input in ["Half Day (AM)", "Half Day (PM)"]
    context.user_data["is_half_day"] = is_half_day
    
    # Create keyboard with cancel option
    cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
    
    if is_half_day:
        await update.message.reply_text("For half day leaves, you can only apply for a single day.\nPlease enter the date of your leave in the format (DD-MM-YYYY):", 
                                     reply_markup=cancel_keyboard)
    else:
        await update.message.reply_text("Please enter the start date of your leave in the format (DD-MM-YYYY):", 
                                     reply_markup=cancel_keyboard)
    
    return START_DATE

async def start_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: Save start date and ask for end date if full day, or go to confirmation if half day"""
    # Ensure username is available
    username = ensure_username(update, context)
    intern_info = get_intern_by_telegram(username)

    today = date.today()
    user_input = update.message.text

    # Check if user wants to cancel
    if user_input == "Cancel":
        return await cancel(update, context)

    try:
        start_date_str = user_input
        start_date = datetime.strptime(start_date_str, "%d-%m-%Y").date()

        # Check if date is in the past
        if start_date < today:
            cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
            await update.message.reply_text("Start date cannot be before today's date. Please enter a valid date (DD-MM-YYYY):", 
                                            reply_markup=cancel_keyboard)
            return START_DATE
        
        # check if start date is past intern end date
        if start_date < intern_info["start_date"] or start_date > intern_info["end_date"]:
            cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
            await update.message.reply_text("Date has to be within internship period. Please enter a valid date (DD-MM-YYYY):", 
                                            reply_markup=cancel_keyboard)
            return START_DATE

        context.user_data["start_date"] = start_date
        
        # If half day, set end date same as start date and go to confirmation
        if context.user_data.get("is_half_day", False):
            context.user_data["end_date"] = start_date
            # Calculate leave duration (0.5 for half day)
            context.user_data["leave_duration"] = 0.5
            # Go directly to confirmation
            return await prepare_confirmation(update, context)
        else:
            # For full day, ask for end date
            cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
            await update.message.reply_text("Please enter the end date of your leave in the format (DD-MM-YYYY):", 
                                        reply_markup=cancel_keyboard)
            return END_DATE

    except ValueError:
        cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
        await update.message.reply_text("Invalid date format. Please enter the date as DD-MM-YYYY.", 
                                        reply_markup=cancel_keyboard)
        return START_DATE

async def end_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5: Save end date and prepare confirmation"""
    # Ensure username is available
    username = ensure_username(update, context)
    intern_info = get_intern_by_telegram(username)
    
    # Get reply from previous step
    user_input = update.message.text
    
    # Check if user wants to cancel
    if user_input == "Cancel":
        return await cancel(update, context)
    
    # Validate and save end date
    try:
        end_date_str = user_input
        end_date = datetime.strptime(end_date_str, "%d-%m-%Y").date()
        context.user_data["end_date"] = end_date
        
        # Check if start date and end date are valid
        start_date = context.user_data["start_date"]
        if start_date > end_date:
            await update.message.reply_text("End date cannot be before start date. Please enter a valid end date (DD-MM-YYYY).")
            return END_DATE
        
        elif end_date < intern_info["start_date"] or end_date > intern_info["end_date"]:
            await update.message.reply_text("End date has to be within your internship duration. Please enter a valid end date (DD-MM-YYYY).")
            return END_DATE

        # Calculate leave duration for full days (excluding weekends)
        leave_duration = 0
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Skip weekends
                leave_duration += 1
            current_date += timedelta(days=1)
        
        context.user_data["leave_duration"] = leave_duration
            
        # Continue to prepare confirmation
        return await prepare_confirmation(update, context)
            
    except ValueError:
        # Create keyboard with cancel option
        cancel_keyboard = ReplyKeyboardMarkup([["Cancel"]], one_time_keyboard=True)
        await update.message.reply_text("Invalid date format. Please enter the end date as DD-MM-YYYY.",
                                      reply_markup=cancel_keyboard)
        return END_DATE

async def prepare_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prepare confirmation message based on leave details"""
    # Ensure username is available
    username = ensure_username(update, context)
    if not username:
        await update.message.reply_text("You are not registered in the system. Please contact HR.", 
                                       reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    
    # Get intern leave balance from database
    intern_info = get_intern_by_telegram(username)
    al_balance = intern_info["al_balance"]
    mc_balance = intern_info["mc_balance"]
    compassionate_balance= intern_info["compassionate_balance"]
    oil_balance = intern_info["oil_balance"]

    # Extract leave details from context
    leave_type = context.user_data["leave_type"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    day_portion = context.user_data["day_portion"]
    leave_duration = context.user_data["leave_duration"]

    # Check if the leave period includes weekends
    has_weekends = False
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            has_weekends = True
            break
        current_date += timedelta(days=1)

    weekends_message = ""
    if has_weekends:
        weekends_message = "\n⚠️ Note: The selected leave period includes weekends. Leave is only counted for weekdays."


    # Check balance and prepare confirmation message for AL
    if leave_type == "Annual Leave":
        if leave_duration > al_balance:
            await update.message.reply_text(
                f"You do not have enough {leave_type} balance. Your current balance is {al_balance} days, but you've requested {leave_duration} days. Please apply for no pay leave instead.",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
            return ConversationHandler.END
        
        new_balance = al_balance - Decimal(str(leave_duration))
        confirmation_message = (f"Leave Type: {leave_type}\n"
                                f"Start Date: {start_date.strftime('%d-%m-%Y')}\n"
                                f"End Date: {end_date.strftime('%d-%m-%Y')}\n"
                                f"Day Portion: {day_portion}\n"
                                f"Leave Duration: {leave_duration} day{'s' if leave_duration > 1 else ''}\n {weekends_message}"
                                f"Remaining AL Balance: {new_balance} days\n\n"
                                "Do you confirm? (Yes/No)")
        context.user_data["new_balance"] = new_balance
        context.user_data["taken_type"] = "al_taken"
        context.user_data["balance_type"] = "al_balance"
        
    # Check balance and prepare confirmation message for MC
    elif leave_type == "Medical Leave":
        if leave_duration > mc_balance:
            await update.message.reply_text(
                f"You do not have enough {leave_type} balance. Your current balance is {mc_balance} days, but you've requested {leave_duration} days. Please apply for no pay leave instead.",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
            return ConversationHandler.END
            
        new_balance = mc_balance - Decimal(str(leave_duration))
        confirmation_message = (f"Leave Type: {leave_type}\n"
                                f"Start Date: {start_date.strftime('%d-%m-%Y')}\n"
                                f"End Date: {end_date.strftime('%d-%m-%Y')}\n"
                                f"Day Portion: {day_portion}\n"
                                f"Leave Duration: {leave_duration} day{'s' if leave_duration > 1 else ''}\n {weekends_message}"
                                f"Remaining MC Balance: {new_balance} days\n\n"
                                "Do you confirm? (Yes/No)")
        context.user_data["new_balance"] = new_balance
        context.user_data["taken_type"] = "mc_taken"
        context.user_data["balance_type"] = "mc_balance"

    # Check balance and prepare confirmation message for Compassionate Leave
    elif leave_type == "Compassionate Leave":
        if leave_duration > compassionate_balance:
            await update.message.reply_text(
                f"You do not have enough {leave_type} balance. Your current balance is {compassionate_balance} days, but you've requested {leave_duration} days. Please apply for no pay leave instead.",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
            return ConversationHandler.END
            
        new_balance = compassionate_balance - Decimal(str(leave_duration))
        confirmation_message = (f"Leave Type: {leave_type}\n"
                                f"Start Date: {start_date.strftime('%d-%m-%Y')}\n"
                                f"End Date: {end_date.strftime('%d-%m-%Y')}\n"
                                f"Day Portion: {day_portion}\n"
                                f"Leave Duration: {leave_duration} day{'s' if leave_duration > 1 else ''}\n {weekends_message}"
                                f"Remaining MC Balance: {new_balance} days\n\n"
                                "Do you confirm? (Yes/No)")
        context.user_data["new_balance"] = new_balance
        context.user_data["taken_type"] = "compassionate_taken"
        context.user_data["balance_type"] = "compassionate_balance"

    # Check balance and prepare confirmation message for OIL
    elif leave_type == "Off in Lieu":
        if leave_duration > oil_balance:
            await update.message.reply_text(
                f"You do not have enough {leave_type} balance. Your current balance is {oil_balance} days, but you've requested {leave_duration} days. Please apply for no pay leave instead.",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
            return ConversationHandler.END
            
        new_balance = oil_balance - Decimal(str(leave_duration))
        confirmation_message = (f"Leave Type: {leave_type}\n"
                                f"Start Date: {start_date.strftime('%d-%m-%Y')}\n"
                                f"End Date: {end_date.strftime('%d-%m-%Y')}\n"
                                f"Day Portion: {day_portion}\n"
                                f"Leave Duration: {leave_duration} day{'s' if leave_duration > 1 else ''}\n {weekends_message}"
                                f"Remaining MC Balance: {new_balance} days\n\n"
                                "Do you confirm? (Yes/No)")
        context.user_data["new_balance"] = new_balance
        context.user_data["taken_type"] = "oil_taken"
        context.user_data["balance_type"] = "oil_balance"
    
    else:  # For other leave types (No Pay)
        confirmation_message = (f"Leave Type: {leave_type}\n"
                               f"Start Date: {start_date.strftime('%d-%m-%Y')}\n"
                               f"End Date: {end_date.strftime('%d-%m-%Y')}\n"
                               f"Day Portion: {day_portion}\n"
                               f"Leave Duration: {leave_duration} day{'s' if leave_duration > 1 else ''}\n\n"
                               "Do you confirm? (Yes/No)")
        
        # Set appropriate taken_type based on leave type
        if leave_type == "No Pay Leave":
            context.user_data["taken_type"] = "npl_taken"

            
        context.user_data["balance_type"] = ""

    # Add Cancel option to the confirmation keyboard
    confirmation_keyboard = ReplyKeyboardMarkup([["Yes", "No"], ["Cancel"]], one_time_keyboard=True)
    await update.message.reply_text(confirmation_message, reply_markup=confirmation_keyboard)
    
    return CONFIRMATION

# Modified confirmation_handler function with better ID generation
async def confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5: Finalize the leave application and send email to supervisor"""
    # Ensure username is available
    username = ensure_username(update, context)
    if not username:
        await update.message.reply_text("You are not registered in the system. Please contact HR.", 
                                       reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    
    # Save user input for confirmation
    user_message = update.message.text
    
    # Check if user wants to cancel
    if user_message == "Cancel":
        return await cancel(update, context)
    
    if user_message.lower() == "yes":
        # Generate a MORE unique application ID using timestamp + uuid
        timestamp = str(int(time.time()))
        unique_id = str(uuid.uuid4())[:8]  # Use first 8 characters of UUID
        application_id = f"{timestamp}_{unique_id}_{username}"
        
        print(f"Generated application ID: {application_id}")  # Debug logging
        
        # Get intern leave balance from database
        intern_info = get_intern_by_telegram(username)
        employee_name = intern_info["name"]
        supervisor_email = intern_info["supervisor_email"]

        leave_application = {
            "chat_id": update.effective_chat.id, 
            "id": application_id,
            "username": username,
            "employee_name": employee_name,
            "leave_type": context.user_data["leave_type"],
            "start_date": context.user_data["start_date"],
            "end_date": context.user_data["end_date"],
            "day_portion": context.user_data["day_portion"],
            "leave_duration": context.user_data["leave_duration"],
            "status": "Pending",
            "submission_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "auto_approve_time": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
            "balance_type": context.user_data.get("balance_type"),
            "new_balance": context.user_data.get("new_balance"),
            "taken_type": context.user_data.get("taken_type"),
            "remarks": ""
        }

        print(f"Created leave application: {leave_application}")
        
        # Initialize leave_applications if it doesn't exist or get cancelled
        if 'leave_applications' not in context.bot_data:
            context.bot_data['leave_applications'] = {}
        
        # Store the application
        context.bot_data['leave_applications'][application_id] = leave_application
        
        # Debug: Print all stored applications (for testing purposes) --> can be removed later
        print(f"Total stored applications: {len(context.bot_data['leave_applications'])}")
        for app_id, app in context.bot_data['leave_applications'].items():
            print(f"App ID: {app_id}, Status: {app['status']}")
        
        # Send email to supervisor with approval/rejection links
        email_sent = await send_supervisor_email(application_id, leave_application, supervisor_email)
        
        if not email_sent:
            await update.message.reply_text("Failed to send email to supervisor. Please try again later.")
            return ConversationHandler.END
        
        # Schedule job to auto-approve after 3 days (simulated 15 minutes for testing)
        job_queue = context.job_queue
        job_queue.run_once(
            auto_approve_leave,
            when=timedelta(minutes=15),  # Change back to days=3 for production
            data={"application_id": application_id, "chat_id": update.effective_chat.id},
            name=f"auto_approve_{application_id}"
        )
        
        await update.message.reply_text(
            f"Your leave application has been submitted and sent to your supervisor for approval.\n"
            "If your supervisor does not respond within 3 days, it will be automatically approved.",
            reply_markup=ReplyKeyboardRemove()
        )

        # if leave_application["leave_type"] in ["Compassionate Leave", "Medical Leave"]:
        #     await update.message.reply_text(
        #         "Remember to submit the official documents for your leave application through the submit documents button in the main menu once your leave has been approved."
        #     )
    else:
        await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())

    # Return to main menu with buttons
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
    return ConversationHandler.END

# Function to send email to supervisor
async def send_supervisor_email(application_id, leave_application, supervisor_email):
    """Send an email to the supervisor with approve/reject links"""
    try:
        # Import email libraries
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Email configuration
        sender_email = os.getenv('SENDER_EMAIL') # Replace with your email
        sender_password = os.getenv('SENDER_PASSWORD')  # Replace with your password or app password

        # Create message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = supervisor_email
        msg['Subject'] = f"Leave Application from {leave_application['employee_name']}"
        
        # Email content with approval/rejection links
        # Note: In production, these would be secure links to your application server
        base_url ="http://127.0.0.1:3001/leave-response"
        approve_url = f"{base_url}?id={application_id}&action=approve"
        reject_url = f"{base_url}?id={application_id}&action=reject"
        
        body = f"""
        Dear Supervisor,
        
        A leave application requires your approval:
        
        Employee: {leave_application['employee_name']}
        Leave Type: {leave_application['leave_type']}
        Start Date: {leave_application['start_date'].strftime('%d-%m-%Y')}
        End Date: {leave_application['end_date'].strftime('%d-%m-%Y')}
        Day Portion: {leave_application['day_portion']}
        Duration: {leave_application['leave_duration']} day{'s' if leave_application['leave_duration'] > 1 else ''}
        
        Please click one of the following links to respond:
        
        APPROVE: {approve_url}
        REJECT: {reject_url}
        
        If no action is taken within 3 days, this leave application will be automatically approved.
        
        Thank you,
        Leave Management System
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to SMTP server and send email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:  # Adjust server settings as needed
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        # Log success
        print(f"Email sent to {supervisor_email} for leave application {application_id}")
        return True
        
    except Exception as e:
        # Log the error
        print(f"Failed to send email: {str(e)}")
        return False

async def auto_approve_leave(context):
    """Automatically approve leave if supervisor hasn't responded in 3 days"""
    job = context.job
    data = job.data
    application_id = data["application_id"]
    chat_id = data["chat_id"]

    # Get leave application from storage
    leave_applications = context.bot_data.get('leave_applications', {})
    leave_application = leave_applications.get(application_id)
    
    if leave_application and leave_application["status"] == "Pending":
        # Update leave status to Approved
        leave_application["status"] = "Auto-Approved"
        leave_application["approval_date"] = datetime.now()
        leave_application["decision_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        remarks_value = ""
        
        # Track no pay leaves by month if it's a No Pay Leave
        if leave_application.get("leave_type") == "No Pay Leave":
            # Generate monthly breakdown of no pay leaves
            monthly_breakdown = {}
            current_date = leave_application["start_date"]
            end_date = leave_application["end_date"]
            
            while current_date <= end_date:
                if current_date.weekday() < 5:  # Skip weekends
                    month_key = current_date.strftime("%Y-%m")
                    if month_key not in monthly_breakdown:
                        monthly_breakdown[month_key] = 0
                    
                    # Add full day or half day based on day_portion
                    day_portion = leave_application.get("day_portion", "Full Day")
                    if day_portion in ["Half Day (AM)", "Half Day (PM)"]:
                        monthly_breakdown[month_key] += 0.5
                    else:
                        monthly_breakdown[month_key] += 1
                
                current_date += timedelta(days=1)
            
            # Format monthly breakdown for remarks
            remarks = "No Pay Leave breakdown: "
            for month, days in monthly_breakdown.items():
                month_name = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
                remarks += f"{month_name}: {days} day(s), "
            remarks_value = remarks.rstrip(", ")
            
        # Update leave balance if needed (for AL and MC leaves) --> in intern data 
        if leave_application.get("balance_type")=="al_balance" or leave_application.get("balance_type")=="mc_balance" or leave_application.get("balance_type")=="compassionate_balance" or leave_application.get("balance_type")=="oil_balance":
            username = leave_application["username"]
            balance_type = leave_application["balance_type"]
            taken_type = leave_application["taken_type"]
            new_balance = leave_application["new_balance"]
            leave_duration = leave_application["leave_duration"]
            print(new_balance,leave_duration)
            # leave_application["remarks"] = remarks_value  # Add remarks to the application
            
            if update_leave_balance(username, balance_type, leave_duration, taken_type) :
                print(f"Leave balance updated for {username}.")
        
        else:
            username = leave_application["username"]
            leave_duration = leave_application["leave_duration"]
            taken_type = leave_application["taken_type"]
            update_leave_taken(username, leave_duration, taken_type)  # Update leave taken field in the database
        
        # Save the updated leave application
        save_leave_application(leave_application)  
        
        # Notify the employee
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Your leave application (ID: {application_id[:8]}) has been automatically approved as your supervisor did not respond within 3 days."
        )
        
        # Notify the supervisor (optional)
        intern_info = get_intern_by_telegram(username)
        supervisor_email = intern_info["supervisor_email"]
        
        try:
            # Send notification email to supervisor
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
                
            # Email configuration
            sender_email = os.getenv('SENDER_EMAIL') # Replace with your email
            sender_password = os.getenv('SENDER_PASSWORD')  # Replace with your password or app password
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = supervisor_email
            msg['Subject'] = f"Leave Application from {leave_application['employee_name']} (Auto-Approved)"
            
            body = f"""
            Dear Supervisor,
            
            The following leave application has been automatically approved due to no response within 3 days:
            
            Employee: {leave_application['employee_name']}
            Leave Type: {leave_application['leave_type']}
            Start Date: {leave_application['start_date'].strftime('%d-%m-%Y')}
            End Date: {leave_application['end_date'].strftime('%d-%m-%Y')}
            Day Portion: {leave_application['day_portion']}
            Duration: {leave_application['leave_duration']} day{'s' if leave_application['leave_duration'] > 1 else ''}
            
            This is an automated message from the Leave Management System.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
                
        except Exception as e:
            print(f"Failed to send auto-approval notification: {str(e)}")

# --------------------------------------
# Section 5: Cancel Leave
# --------------------------------------
            
# Entry point for cancel leave
async def cancel_leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> int:
    """Start the leave cancellation process by showing list of approved leaves"""
    # Ensure username is available
    username = ensure_username(update, context)
    if not username:
        message = "You are not registered in the system. Please contact HR."
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return ConversationHandler.END
    
    # Get approved leaves from the database
    approved_leaves = get_approved_leaves(username)

    if not approved_leaves:
        message = "You don't have any upcoming approved leaves to cancel."
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=back_button())
        else:
            await update.message.reply_text(message, reply_markup=back_button())
        return ConversationHandler.END
    
    # Create keyboard with leave options
    keyboard = []
    for i, leave in enumerate(approved_leaves):
        # Safer date formatting that handles various types
        start_date = leave['start_date']
        end_date = leave['end_date']
        
        # Convert to string if it's a date object
        if hasattr(start_date, 'strftime'):
            start_date = start_date.strftime('%d-%m-%Y')
        
        if hasattr(end_date, 'strftime'):
            end_date = end_date.strftime('%d-%m-%Y')
        
        leave_text = f"{leave['leave_type']} ({start_date} to {end_date})"
        keyboard.append([leave_text])
    
    keyboard.append(["Cancel"])  # Add Cancel button
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    # Store approved leaves in context for later reference
    context.user_data["approved_leaves"] = approved_leaves
    
    message = "Please select which leave you want to cancel:"
    if update.callback_query:
        await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return CHOOSE_LEAVE_TO_CANCEL

# Function to choose leave to cancel
async def choose_leave_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection of which leave to cancel"""
    user_input = update.message.text
    
    # Check if user wants to cancel the operation
    if user_input == "Cancel":
        await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
        return ConversationHandler.END
    
    # Find the selected leave from stored approved leaves
    approved_leaves = context.user_data.get("approved_leaves", [])
    selected_leave = None
    
    for leave in approved_leaves:
        # Safer date formatting that handles various types
        start_date = leave['start_date']
        end_date = leave['end_date']
        
        # Convert to string if it's a date object
        if hasattr(start_date, 'strftime'):
            start_date = start_date.strftime('%d-%m-%Y')
        
        if hasattr(end_date, 'strftime'):
            end_date = end_date.strftime('%d-%m-%Y')
            
        leave_text = f"{leave['leave_type']} ({start_date} to {end_date})"
        
        if leave_text == user_input:
            selected_leave = leave
            break
    
    if not selected_leave:
        await update.message.reply_text("Invalid selection. Please try again.")
        return CHOOSE_LEAVE_TO_CANCEL
    
    # Store the selected leave for confirmation
    context.user_data["selected_leave"] = selected_leave
    
    # Format dates for display
    start_date = selected_leave['start_date']
    end_date = selected_leave['end_date']
    
    # Convert to string if it's a date object
    if hasattr(start_date, 'strftime'):
        start_date = start_date.strftime('%d-%m-%Y')
    
    if hasattr(end_date, 'strftime'):
        end_date = end_date.strftime('%d-%m-%Y')
    
    # Ask for confirmation
    confirmation_message = (
        f"You are about to cancel the following leave:\n\n"
        f"Leave Type: {selected_leave['leave_type']}\n"
        f"Start Date: {start_date}\n"
        f"End Date: {end_date}\n"
    )
    
    if selected_leave['day_portion'] != "Full Day":
        confirmation_message += f"Day Portion: {selected_leave['day_portion']}\n"
        
    confirmation_message += (
        f"Leave Duration: {selected_leave['leave_duration']} day{'s' if selected_leave['leave_duration'] > 1 else ''}\n\n"
        "Are you sure you want to cancel this leave? (Yes/No)"
    )
    
    confirmation_keyboard = ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True)
    await update.message.reply_text(confirmation_message, reply_markup=confirmation_keyboard)
    
    return CONFIRM_CANCEL

# Confirmation notification handler for leave cancellation
async def confirm_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the confirmation of leave cancellation"""
    username = ensure_username(update, context)
    user_input = update.message.text.lower()
    
    if user_input != "yes":
        await update.message.reply_text("Leave cancellation aborted.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
        return ConversationHandler.END
    
    # Get the selected leave
    selected_leave = context.user_data.get("selected_leave")
    if not selected_leave:
        await update.message.reply_text("Error: Leave information not found.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
        return ConversationHandler.END
    
    # Cancel the leave in the database
    success = cancel_leave_application(selected_leave['application_id'], username)
    
    if success:
        await update.message.reply_text(
            "Your leave has been successfully cancelled and your leave balance has been restored.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Notify supervisor about cancellation
        await notify_supervisor_of_cancellation(selected_leave, username)
    else:
        await update.message.reply_text(
            "There was an error cancelling your leave. Please contact HR for assistance.",
            reply_markup=ReplyKeyboardRemove()
        )
    
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
    return ConversationHandler.END

# Alerting supervisor about leave cancellation
async def notify_supervisor_of_cancellation(leave_details, username):
    """Send an email to the supervisor about the leave cancellation"""
    try:
        # Get intern info including supervisor email
        intern_info = get_intern_by_telegram(username)
        if not intern_info or not intern_info.get('supervisor_email'):
            print("Could not find supervisor email")
            return False
        
        # Format dates
        start_date = leave_details['start_date'].strftime('%d-%m-%Y') if isinstance(leave_details['start_date'], date) else leave_details['start_date']
        end_date = leave_details['end_date'].strftime('%d-%m-%Y') if isinstance(leave_details['end_date'], date) else leave_details['end_date']
        
        # Import email libraries
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Email configuration
        sender_email = os.getenv('SENDER_EMAIL') # Replace with your email
        sender_password = os.getenv('SENDER_PASSWORD')  # Replace with your password or app password
        supervisor_email = intern_info['supervisor_email']
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = supervisor_email
        msg['Subject'] = f"Leave Cancellation Notice - {intern_info['name']}"
        
        body = f"""
        Dear Supervisor,
        
        This is to inform you that {intern_info['name']} has cancelled the following leave:
        
        Leave Type: {leave_details['leave_type']}
        Start Date: {start_date}
        End Date: {end_date}
        Duration: {leave_details['leave_duration']} day(s)
        
        The leave entitlements have been restored to the intern's balance.
        
        Thank you,
        Leave Management System
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to SMTP server and send email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        print(f"Cancellation notification sent to {supervisor_email}")
        return True
        
    except Exception as e:
        print(f"Failed to send cancellation notification: {str(e)}")
        return False



# --------------------------------------
# Section 5: Main Function
# --------------------------------------

# cacnel function to go back to main menu
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Leave application cancelled.", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())
    return ConversationHandler.END

# Main function to start the bot and set up handlers
def main() -> None:
    """Main function to start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_web_server, args=(application,))
    flask_thread.daemon = True
    flask_thread.start()

    # Set up the conversation handler for leave application with new DOCUMENT_VERIFICATION state
    apply_leave_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("applyleave", apply_leave_start),
            CallbackQueryHandler(apply_leave_start, pattern="^apply_leave$")
        ],
    states={
        LEAVE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_type_handler)],
        DOCUMENT_SUBMISSION: [CallbackQueryHandler(document_submission_handler)],
        DAY_PORTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, day_portion_handler)],
        START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_date_handler)],
        END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, end_date_handler)],
        CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmation_handler)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add the new cancel leave conversation handler
    cancel_leave_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("cancelleave", cancel_leave_start),
            CallbackQueryHandler(cancel_leave_start, pattern="^cancel_leave$")
        ],
        states={
            CHOOSE_LEAVE_TO_CANCEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_leave_handler)],
            CONFIRM_CANCEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_cancel_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Register all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(apply_leave_conversation)
    application.add_handler(cancel_leave_conversation)  # Add the new conversation handler
    
    # This handler should come after conversation handlers to avoid conflict
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Run the bot
    application.run_polling()
    
if __name__ == "__main__":
    main()