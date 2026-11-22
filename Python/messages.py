"""messages.py - status code -> text.  The ONLY place with user-facing sentences.

Numbers inside the sentences (500, 25,000, ...) come from the assembly code through
GetRule, so they can never drift away from the real rules.

VERSION 2 additions (search for "VERSION 2"): loader texts, transaction receipt texts,
the "view the AsmBank app" hint.
"""
import bridge


def signup_msg(result_code):
    """Text for the result of bridge.sign_up()."""
    return {1:  "Account created! You can log in now.",
            -1: "That username is already taken.",
            -2: "Username must be 3-15 letters or digits.",
            -3: "The bank is full (maximum users reached).",
            -4: "PIN must be exactly 4 digits."}.get(result_code, f"Unknown error ({result_code})")

def login_msg(result_code, user_name):
    """Text for the result of bridge.login()."""
    if result_code == 1:
        return "Welcome!"
    if result_code == 0:
        return f"Wrong PIN. {bridge.attempts_left(user_name)} attempt(s) left."
    if result_code == -1:
        return "No such user."
    if result_code == -2:
        return ("Your account has been locked after too many incorrect PIN attempts.\n"
                "Please contact AsmBank customer support to unlock it.")
    return f"Unknown error ({result_code})"

def withdraw_msg(result_code):
    """Text for the result of bridge.withdraw()."""
    withdraw_unit = bridge.get_rule(0)
    maximum_withdrawal = bridge.get_rule(1)
    return {1:  "Please take your cash.",
            0:  "Insufficient balance.",
            -1: "Please log in first.",
            -2: "Enter a whole number (digits only).",
            -3: f"Amount must be a multiple of Rs {withdraw_unit}.",
            -4: f"Maximum per withdrawal is Rs {maximum_withdrawal:,}."}.get(
                result_code, f"Unknown error ({result_code})")

def deposit_msg(result_code):
    """Text for the result of bridge.deposit()."""
    maximum_deposit = bridge.get_rule(2)
    return {1:  "Deposit successful.",
            -1: "Please log in first.",
            -2: "Enter a whole number (digits only).",
            -4: f"Maximum per deposit is Rs {maximum_deposit:,}.",
            -5: "This deposit would exceed the account limit."}.get(
                result_code, f"Unknown error ({result_code})")

def format_rupees(amount):
    """Display helper: 7500 -> 'Rs 7,500'."""
    return f"Rs {amount:,}"


# ---------------------------------------------------------------------------
# Extra sentences used by the GUI (app.py)
# ---------------------------------------------------------------------------
def limits_text():
    """The ATM limits, read from the assembly rules, for the dashboard."""
    withdraw_unit = bridge.get_rule(0)
    maximum_withdrawal = bridge.get_rule(1)
    maximum_deposit = bridge.get_rule(2)
    return (f"Withdraw in multiples of Rs {withdraw_unit:,}, up to Rs {maximum_withdrawal:,} at a time.\n"
            f"Deposit up to Rs {maximum_deposit:,} at a time.")

def save_failed_msg():
    """Shown when users.csv could not be written (for example it is open in Excel)."""
    return "Done in memory, but users.csv could not be saved. Close it if it is open in Excel."

def auto_logout_msg(timeout_seconds):
    """Shown on the welcome screen after the inactivity timeout."""
    return f"You were logged out after {timeout_seconds} seconds of inactivity."

def rejected_rows_msg(skipped_count):
    """Start-up warning when ImportUser rejected rows of users.csv."""
    return (f"{skipped_count} row(s) in users.csv were invalid and were skipped.\n\n"
            "A copy of the original file was saved as users.csv.bak.")


# ---------------------------------------------------------------------------
# VERSION 2 (NEW): sentences for the loader screen
# ---------------------------------------------------------------------------
def loader_texts(is_sign_up):
    """Return (title, four stage texts) for the loader screen.

    The four stage texts match the four progress stages 0-25 %, 25-65 %, 65-90 %, 90-100 %.
    """
    if is_sign_up:
        return ("Creating your account",
                ("Checking your details", "Creating your account",
                 "Securing your PIN", "Finishing up"))
    return ("Signing you in",
            ("Verifying your PIN", "Opening your account",
             "Loading your balance", "Almost ready"))


# ---------------------------------------------------------------------------
# VERSION 2 (NEW): sentences for the transaction receipt
# ---------------------------------------------------------------------------
def transaction_title_msg(transaction_kind, amount):
    """'withdrawal', 2500 -> 'Withdrawal of Rs 2,500'   (kind is 'deposit' or 'withdrawal')."""
    kind_text = {"deposit": "Deposit", "withdrawal": "Withdrawal"}.get(transaction_kind, "Transaction")
    return f"{kind_text} of {format_rupees(amount)}"

def format_timestamp(moment):
    """datetime -> '15 Oct 2026, 02:32:08 PM'."""
    return moment.strftime("%d %b %Y, %I:%M:%S %p")

def format_reference(moment):
    """Receipt reference such as 'ASM-261015-143025-123456' (date + timestamp + microseconds)."""
    return f"ASM-{moment:%y%m%d-%H%M%S-%f}"

def transaction_details_msg(moment, balance_after):
    """Two small lines shown under the green message after a successful transaction."""
    return (f"Date: {format_timestamp(moment)}\n"
            f"ID: {format_reference(moment)}\n" 
            f"Balance: {format_rupees(balance_after)}")

def bank_app_hint_msg():
    """Hint shown in the small shadow box: a real ATM receipt is short, the app has the full list."""
    return "Want your complete transaction history? View it in the AsmBank app."
