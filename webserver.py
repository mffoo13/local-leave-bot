from flask import Flask, request, jsonify
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from db_utils import get_registered_interns, get_intern_by_telegram, update_leave_balance, save_leave_application, update_leave_taken
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # Add these imports


app = Flask(__name__)

# This will be set by the main bot
bot_context = None

@app.route('/leave-response', methods=['GET'])
def handle_leave_response():
    """Handle supervisor's approve/reject response from email links"""
    application_id = request.args.get('id')
    action = request.args.get('action')
    
    if not bot_context:
        return jsonify({"status": "error", "message": "Bot not initialized"}), 500
        
    leave_applications = bot_context.bot_data.get('leave_applications', {})
    leave_application = leave_applications.get(application_id)
    
    if not leave_application or leave_application["status"] != "Pending":
        return jsonify({"status": "error", "message": "Invalid or expired application"}), 400
    
    # intern_data = pd.read_csv("Sample Intern Data.csv")
    # leave_logs = pd.read_csv("Leave Logs.csv")

    # Get Datetime of approval/rejection
    decision_time = datetime.now()
    leave_application["decision_time"] = decision_time.strftime("%Y-%m-%d %H:%M:%S")

    remarks_value = ""  # Initialize remarks value

    # Update status based on action
    if action == "approve":
        leave_application["status"] = "Approved"
        
        # # Track no pay leaves by month 

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
                if current_date == leave_application["start_date"] and current_date == leave_application["end_date"]:
                    # Single day leave with possibly AM/PM option
                    day_portion = leave_application.get("day_portion", "Full Day")
                    if day_portion in ["AM Only", "PM Only"]:
                        monthly_breakdown[month_key] += 0.5
                    else:
                        monthly_breakdown[month_key] += 1
                else:
                    monthly_breakdown[month_key] += 1
            
            current_date += timedelta(days=1)
        
        # Format monthly breakdown for remarks
        remarks = "Leave breakdown: "
        for month, days in monthly_breakdown.items():
            month_name = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
            remarks += f"{month_name}: {days} day(s), "
        remarks_value = remarks.rstrip(", ")
        leave_application["remarks"] = remarks_value

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

        message=f'You have <b>approved</b> {leave_application["leave_type"]} for {leave_application["employee_name"]} to be taken from {leave_application["start_date"]} to {leave_application["end_date"]}. Duration: {leave_application["leave_duration"]} days. The candidate has been notified.'
        
            


    elif action == "reject":
        leave_application["status"] = "Rejected"
        message=f'You have <b>rejected</b> {leave_application["leave_type"]} for {leave_application["employee_name"]} to be taken from {leave_application["start_date"]} to {leave_application["end_date"]}. Duration: {leave_application["leave_duration"]} days. The candidate has been notified.'
        
        # No remarks needed for rejected applications
        
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    

    save_leave_application(leave_application)  # Save to database
    
    
    # Cancel auto-approval job
    job_queue = bot_context.job_queue
    current_jobs = job_queue.get_jobs_by_name(f"auto_approve_{application_id}")
    for job in current_jobs:
        job.schedule_removal()
    
    # Notify employee
    if 'chat_id' in leave_application:
        try:
            print("Notifying employee...")
            
            # First send the notification about leave approval/rejection
            asyncio.run(
                bot_context.bot.send_message(
                    chat_id=leave_application["chat_id"],
                    text=f"Your {leave_application.get('leave_type', 'Unknown')} from {leave_application['start_date']} to {leave_application['end_date']}, has been {leave_application['status'].lower()} by your supervisor."
                )
            )
            
            # Then send the main menu
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            
            # Create main menu keyboard - must match your main_menu() function
            keyboard = [
                [InlineKeyboardButton("Check Leave Balance", callback_data="balance")],
                [InlineKeyboardButton("Apply for Leave", callback_data="apply_leave")],
                [InlineKeyboardButton("Cancel Leave", callback_data="cancel_leave")],
                [InlineKeyboardButton("Submit Documents", url=os.getenv("FORM_URL"))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send main menu
            asyncio.run(
                bot_context.bot.send_message(
                    chat_id=leave_application["chat_id"],
                    text="Welcome! Choose an option:",
                    reply_markup=reply_markup
                )
            )
            
            print("Notified employee and sent main menu.")
        except Exception as e:
            print(f"Failed to notify employee: {e}")
    
    # return jsonify({"status": "success", "action": action, "application_id": application_id})
    return message, 200, {"Content-Type": "text/html"}

def run_web_server(context):
    global bot_context
    bot_context = context
    port=int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0',port=port)