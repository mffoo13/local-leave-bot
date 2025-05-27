# db_pool.py (revised for establishing PostgreSQL connection via pgAdmin)
import psycopg2
from psycopg2 import pool
from datetime import datetime, date
import os
from dotenv import load_dotenv
import pandas as pd


# Load environment variables
load_dotenv()

# Create a connection pool
connection_pool = None

# Get database configuration from environment variables
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT")
}

# Initialize the connection pool
def init_db_pool():
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,
                host=DB_CONFIG["host"],
                database=DB_CONFIG["database"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                port=DB_CONFIG["port"]
            )
            print("Database connection pool initialized.")
        except Exception as e:
            print(f"Failed to initialize database pool: {e}")
    return connection_pool

def get_connection():
    if connection_pool is None:
        init_db_pool()
    return connection_pool.getconn()

def release_connection(conn):
    if connection_pool:
        connection_pool.putconn(conn)

def adapt_date(date_obj):
    if isinstance(date_obj, date):
        return date_obj
    try:
        return datetime.strptime(date_obj, "%d-%m-%Y").date()
    except (ValueError, TypeError):
        return date_obj

# Create a new table for interns if it doesn't exist (should only be done once for initial setup) 
# and updates arrival of new interns by editing interns_new.csv

def create_interns_table_from_csv(csv_file_path):
    import csv
    import pandas as pd
    from datetime import datetime

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Check if the interns_new table already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'interns_new'
            )
        """)
        table_exists = cursor.fetchone()[0]

        if not table_exists:
            print("Creating 'interns_new' table as it doesn't exist.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interns_new (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    telegram_handle VARCHAR(100) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    supervisor_email VARCHAR(255),
                    al_entitlement NUMERIC(5,1) DEFAULT 0,
                    mc_entitlement NUMERIC(5,1) DEFAULT 0,
                    compassionate_entitlement NUMERIC(5,1) DEFAULT 3,
                    oil_entitlement NUMERIC(5,1) DEFAULT 0,
                    al_taken NUMERIC(5,1) DEFAULT 0,
                    mc_taken NUMERIC(5,1) DEFAULT 0,
                    compassionate_taken NUMERIC(5,1) DEFAULT 0,
                    oil_taken NUMERIC(5,1) DEFAULT 0,
                    npl_taken NUMERIC(5,1) DEFAULT 0,
                    al_balance NUMERIC(5,1) DEFAULT 0,
                    mc_balance NUMERIC(5,1) DEFAULT 0,
                    compassionate_balance NUMERIC(5,1) DEFAULT 3,
                    oil_balance NUMERIC(5,1) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'Active'
                )
            """)
        else:
            print("Table 'interns_new' already exists, proceeding to import data.")

        cursor.execute("""
            UPDATE interns_new
            SET status = 'Completed'
            WHERE end_date < CURRENT_DATE
            AND status = 'Active'
        """)
        conn.commit()
        print("Updated status to 'Completed' for interns whose end date has passed.")

        # Have to edit the CSV file to match the expected column names in case of any changes
        mappings = {
            'name': 'Name of Intern',
            'telegram_handle': 'Telegram Handle',
            'start_date': 'Start Date',
            'end_date': 'End Date',
            'supervisor_email': 'Supervisor Email',
            'al_entitlement': 'Bal Vacation Leave Taken',
            'mc_entitlement': 'Bal Medical Leave',
            'oil_entitlement': 'Balance OIL Taken'  
        }

        df = pd.read_csv(csv_file_path)

        # drop rows where 'Telegram Handle' is NaN
        df = df.dropna(subset=['Telegram Handle'])
        
        # Set date to correct format
        df['start_date'] = pd.to_datetime(df[mappings['start_date']].str.strip(), format="%d-%b-%y").dt.strftime("%Y-%m-%d")
        df['end_date'] = pd.to_datetime(df[mappings['end_date']].str.strip(), format="%d-%b-%y").dt.strftime("%Y-%m-%d")

        processed_interns = set()

        # Iterate through the DataFrame and process each intern --> This part handles the logic of checking for duplicates and updating or inserting records
        for _, row in df.iterrows():
            telegram_handle = row[mappings['telegram_handle']].strip()
            start_date = row['start_date']
            end_date = row['end_date']

            intern_key = f"{telegram_handle}_{start_date}_{end_date}"
            if intern_key in processed_interns:
                print(f"Skipping duplicate entry in CSV for {telegram_handle} ({start_date} to {end_date})")
                continue

            processed_interns.add(intern_key)

            # Checks if intern period and status will be adjusted accordingly
            new_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            new_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            today = datetime.now().date()
            if new_start_date > today:
                current_status = 'Pending Start'
            elif new_end_date >= today:
                current_status = 'Active'
            else:
                current_status = 'Completed'

            al_entitlement = float(row[mappings['al_entitlement']]) if pd.notna(row[mappings['al_entitlement']]) else 0
            mc_entitlement = float(row[mappings['mc_entitlement']]) if pd.notna(row[mappings['mc_entitlement']]) else 0
            # Set default compassionate entitlement (3 days)
            compassionate_entitlement = 3.0
            # Added oil entitlement
            oil_entitlement = float(row[mappings['oil_entitlement']]) if pd.notna(row[mappings['oil_entitlement']]) else 0

            # Check if the intern already exists with the same telegram handle and dates
            cursor.execute("""
                SELECT id, al_taken, mc_taken, compassionate_taken, oil_taken, status
                FROM interns_new 
                WHERE telegram_handle = %s
                AND start_date = %s
                AND end_date = %s
            """, (telegram_handle, start_date, end_date))

            exact_match = cursor.fetchone()

            # If an exact match is found, update the record
            if exact_match:
                intern_id = exact_match[0]
                al_taken = float(exact_match[1] or 0)
                mc_taken = float(exact_match[2] or 0)
                compassionate_taken = float(exact_match[3] or 0)
                oil_taken = float(exact_match[4] or 0)  # Added oil_taken
                
                al_balance = al_entitlement - al_taken
                mc_balance = mc_entitlement - mc_taken
                # Calculate compassionate balance
                compassionate_balance = compassionate_entitlement - compassionate_taken
                # Calculate oil balance
                oil_balance = oil_entitlement - oil_taken

                
                print(f"Updating exact match record for {telegram_handle} ({start_date} to {end_date})")
                cursor.execute("""
                    UPDATE interns_new
                    SET name = %s,
                        supervisor_email = %s,
                        al_entitlement = %s,
                        mc_entitlement = %s,
                        compassionate_entitlement = %s,
                        oil_entitlement = %s,
                        al_balance = %s,
                        mc_balance = %s,
                        compassionate_balance = %s,
                        oil_balance = %s,
                        status = %s
                    WHERE id = %s
                """, (
                    row[mappings['name']].strip(),
                    row[mappings['supervisor_email']].strip() if pd.notna(row[mappings['supervisor_email']]) else None,
                    al_entitlement,
                    mc_entitlement,
                    compassionate_entitlement,
                    oil_entitlement,
                    al_balance,
                    mc_balance,
                    compassionate_balance,
                    oil_balance,
                    current_status,
                    intern_id
                ))
            else:
                if current_status == 'Completed':
                    cursor.execute("""
                        SELECT COUNT(*)
                        FROM interns_new 
                        WHERE telegram_handle = %s
                        AND status = 'Completed'
                        AND start_date = %s
                        AND end_date = %s
                    """, (telegram_handle, start_date, end_date))

                    duplicate_count = cursor.fetchone()[0]
                    if duplicate_count > 0:
                        print(f"Skipping duplicate completed internship for {telegram_handle} ({start_date} to {end_date})")
                        continue

                cursor.execute("""
                    SELECT id, al_taken, mc_taken, compassionate_taken, oil_taken, status, start_date, end_date
                    FROM interns_new 
                    WHERE telegram_handle = %s
                    ORDER BY status = 'Active' DESC, id DESC
                    LIMIT 1
                """, (telegram_handle,))
                existing_intern = cursor.fetchone()

                if existing_intern and (existing_intern[5] == 'Active' or existing_intern[5] == 'Pending Start'):  # Updated index for status
                    intern_id = existing_intern[0]
                    al_taken = float(existing_intern[1] or 0)
                    mc_taken = float(existing_intern[2] or 0)
                    compassionate_taken = float(existing_intern[3] or 0)
                    oil_taken = float(existing_intern[4] or 0)  # Added oil_taken
                    
                    al_balance = al_entitlement - al_taken
                    mc_balance = mc_entitlement - mc_taken
                    # Calculate compassionate balance
                    compassionate_balance = compassionate_entitlement - compassionate_taken
                    # Calculate oil balance
                    oil_balance = oil_entitlement - oil_taken

                    print(f"Updating existing active record for {telegram_handle}")
                    cursor.execute("""
                        UPDATE interns_new
                        SET name = %s,
                            start_date = %s,
                            end_date = %s,
                            supervisor_email = %s,
                            al_entitlement = %s,
                            mc_entitlement = %s,
                            compassionate_entitlement = %s,
                            oil_entitlement = %s,
                            al_balance = %s,
                            mc_balance = %s,
                            compassionate_balance = %s,
                            oil_balance = %s,
                            status = %s
                        WHERE id = %s
                    """, (
                        row[mappings['name']].strip(),
                        start_date,
                        end_date,
                        row[mappings['supervisor_email']].strip() if pd.notna(row[mappings['supervisor_email']]) else None,
                        al_entitlement,
                        mc_entitlement,
                        compassionate_entitlement,
                        oil_entitlement,
                        al_balance,
                        mc_balance,
                        compassionate_balance,
                        oil_balance,
                        current_status,
                        intern_id
                    ))

                else:
                    # For new records, taken values are 0 by default
                    al_balance = al_entitlement
                    mc_balance = mc_entitlement
                    compassionate_balance = compassionate_entitlement
                    oil_balance = oil_entitlement  # Added oil_balance for new records

                    if current_status == 'Completed':
                        print(f"Creating new completed record for {telegram_handle} ({start_date} to {end_date})")

                    cursor.execute("""
                        INSERT INTO interns_new (
                            name, 
                            telegram_handle, 
                            start_date, 
                            end_date, 
                            supervisor_email, 
                            al_entitlement,
                            mc_entitlement,
                            compassionate_entitlement,
                            oil_entitlement,
                            al_balance, 
                            mc_balance,
                            compassionate_balance,
                            oil_balance,
                            status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        row[mappings['name']].strip(),
                        telegram_handle,
                        start_date,
                        end_date,
                        row[mappings['supervisor_email']].strip() if pd.notna(row[mappings['supervisor_email']]) else None,
                        al_entitlement,
                        mc_entitlement,
                        compassionate_entitlement,
                        oil_entitlement,
                        al_balance,
                        mc_balance,
                        compassionate_balance,
                        oil_balance,
                        current_status
                    ))

        conn.commit()
        print(f"Successfully processed intern data from {csv_file_path}")
        return True

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error: {e}")
        return False

# This function creates a new table for leave logs if it doesn't exist
def create_leave_logs_new():
    conn = None
    try:
        conn = get_connection()
        if conn is None:
            print("Failed to get DB connection.")
            return False
        
        cursor = conn.cursor()
        print("Connected to database, creating leave_logs_new table...")

        create_table_sql = """
            CREATE TABLE IF NOT EXISTS leave_logs_new (
                application_id VARCHAR(100) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                submission_date TIMESTAMP NOT NULL,
                supervisor_review TIMESTAMP,
                leave_type VARCHAR(50) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                number_of_leaves_taken NUMERIC(5,1) NOT NULL,
                day_portion VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL,
                remarks TEXT
            )
        """

        cursor.execute(create_table_sql)
        conn.commit()
        print("Successfully created leave_logs_new table")
        return True
    
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error while creating leave_logs_new: {e}")
        return False
    
    finally:
        if conn:
            release_connection(conn)

 # Creation of tables if needed
create_interns_table_from_csv(os.getenv("INTERNS_DB"))
create_leave_logs_new()        

# This function retrieves all registered interns and their IDs
def get_registered_interns():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, telegram_handle FROM interns_new")
        rows = cursor.fetchall()
        return {row[2]: row[0] for row in rows}
    except Exception as e:
        print(f"Database error: {e}")
        return {}
    finally:
        if conn:
            release_connection(conn)

# This function retrieves intern information by their Telegram handle
def get_intern_by_telegram(telegram_handle):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, telegram_handle, supervisor_email, al_balance, mc_balance, end_date, start_date, compassionate_balance, oil_balance
            FROM interns_new 
            WHERE telegram_handle = %s
        """, (telegram_handle,))
        intern = cursor.fetchone()
        if intern:
            return {
                'id': intern[0],
                'start_date': intern[7],
                'end_date': intern[6],
                'name': intern[1],
                'telegram_handle': intern[2],
                'supervisor_email': intern[3],
                'al_balance': intern[4],
                'mc_balance': intern[5],
                'compassionate_balance':intern[8],
                'oil_balance': intern[9]
            }
        return None
    except Exception as e:
        print(f"Database error: {e}")
        return None
    finally:
        if conn:
            release_connection(conn)

# This function updates the leave balance in the database
def update_leave_balance(username, balance_type, leave_duration, taken_type):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Deduct leave balance
        cursor.execute(
            f"UPDATE interns_new SET {balance_type} = COALESCE({balance_type}, 0) - %s WHERE telegram_handle = %s",
            (leave_duration, username)
        )

        # Update leave taken field
        cursor.execute(
            f"UPDATE interns_new SET {taken_type} = COALESCE({taken_type}, 0) + %s WHERE telegram_handle = %s",
            (leave_duration, username)
        )

        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)

# This function is used to just update the leave taken field in the database (for leaves that are not AL or MC)
def update_leave_taken(username, leave_duration, taken_type):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Update leave taken field
        cursor.execute(
            f"UPDATE interns_new SET {taken_type} = COALESCE({taken_type}, 0) + %s WHERE telegram_handle = %s",
            (leave_duration, username)
        )

        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)

# This function saves a leave application to the database after intern take leave
def save_leave_application(application):
    print("Function called with application:", application['id'])  # Debug at start
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print("About to execute INSERT")  # Debug before insert
        cursor.execute("""
            INSERT INTO leave_logs_new 
            (application_id, name, submission_date, supervisor_review, leave_type, 
             start_date, end_date, number_of_leaves_taken, day_portion, status, remarks)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            application['id'],
            application['employee_name'],
            application['submission_time'],
            application.get('decision_time', None),
            application['leave_type'],
            adapt_date(application['start_date']),
            adapt_date(application['end_date']),
            application['leave_duration'],
            application['day_portion'],
            application['status'],
            application["remarks"]
        ))
        print("Insert executed successfully",flush=True)  # Debug after insert
        conn.commit()
        print("Commit successful",flush=True)  # Debug after commit
        print(f"Leave application on {adapt_date(application['start_date'])} for {application['employee_name']} saved successfully in leave_logs_new",flush=True)
        return True
    except Exception as e:
        print(f"Error occurred: {e}")  # Print any exceptions
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# This function retrieves the status of a leave application by its ID
def get_leave_application(application_id):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM leave_logs_new WHERE application_id = %s", (application_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"Database error: {e}")
        return None
    finally:
        if conn:
            release_connection(conn)

# This function retrieves all approved leaves for a given intern by their Telegram handle
def get_approved_leaves(telegram_handle):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT application_id, name, leave_type, start_date, end_date, 
                   number_of_leaves_taken, day_portion, status, remarks
            FROM leave_logs_new  
            WHERE name = (SELECT name FROM interns_new WHERE telegram_handle = %s)
            AND status IN ('Approved', 'Auto-Approved')
            AND start_date >= CURRENT_DATE
            ORDER BY start_date ASC
        """, (telegram_handle,))
        
        leaves = []
        for row in cursor.fetchall():
            leaves.append({
                'application_id': row[0],
                'name': row[1],
                'leave_type': row[2],
                'start_date': row[3],
                'end_date': row[4],
                'leave_duration': row[5],
                'day_portion': row[6],
                'status': row[7],
                'remarks': row[8]
            })
        return leaves
    except Exception as e:
        print(f"Database error: {e}")
        return []
    finally:
        if conn:
            release_connection(conn)

# This function cancels a leave application and restores the leave balance
def cancel_leave_application(application_id, telegram_handle):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get the leave details first
        cursor.execute("""
            SELECT leave_type, number_of_leaves_taken 
            FROM leave_logs_new  
            WHERE application_id = %s
        """, (application_id,))
        
        leave_info = cursor.fetchone()
        if not leave_info:
            return False
            
        leave_type, leave_duration = leave_info
        
        # Update status to Cancelled
        cursor.execute("""
            UPDATE leave_logs_new  
            SET status = 'Cancelled', 
                remarks = CONCAT(COALESCE(remarks, ''), ' [Cancelled by intern]')
            WHERE application_id = %s
        """, (application_id,))
        
        # Restore leave balance based on leave type
        if leave_type == 'Annual Leave':
            cursor.execute("""
                UPDATE interns_new 
                SET al_balance = al_balance + %s,
                    al_taken = GREATEST(0, al_taken - %s)
                WHERE telegram_handle = %s
            """, (leave_duration, leave_duration, telegram_handle))
        elif leave_type == 'Medical Leave':
            cursor.execute("""
                UPDATE interns_new 
                SET mc_balance = mc_balance + %s,
                    mc_taken = GREATEST(0, mc_taken - %s)
                WHERE telegram_handle = %s
            """, (leave_duration, leave_duration, telegram_handle))
        elif leave_type == 'No Pay Leave':
            cursor.execute("""
                UPDATE interns_new 
                SET npl_taken = GREATEST(0, npl_taken - %s)
                WHERE telegram_handle = %s
            """, (leave_duration, telegram_handle))
        elif leave_type == 'Compassionate Leave':
            cursor.execute("""
                UPDATE interns_new 
                SET compassionate_taken = GREATEST(0, compassionate_taken - %s)
                WHERE telegram_handle = %s
            """, (leave_duration, telegram_handle))
        elif leave_type == 'Off in Lieu':
            cursor.execute("""
                UPDATE interns_new 
                SET oil_taken = GREATEST(0, oil_taken - %s)
                WHERE telegram_handle = %s
            """, (leave_duration, telegram_handle))
        
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error when cancelling leave: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)

# This function deletes a user from the interns_new and leave_logs_new tables (for admin and coding use whenever needed)
def delete_user(telegram_handle):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Delete from interns_new table
        cursor.execute("""
            DELETE FROM interns_new 
            WHERE telegram_handle = %s
        """, (telegram_handle,))
        
        # Delete from leave_logs_new table
        cursor.execute("""
            DELETE FROM leave_logs_new 
            WHERE name = (SELECT name FROM interns_new WHERE telegram_handle = %s)
        """, (telegram_handle,))
        
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database error when deleting user: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)