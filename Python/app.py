"""app.py - the AsmBank ATM graphical interface (CustomTkinter, dark mode).

RULES OF THIS FILE (project documentation, section 14)
  * NO business rules here. Every button sends the RAW text to `bridge`, receives a
    status code, and shows the sentence that `messages` provides for that code.
  * The typing helpers (digits only, maximum length) are only a convenience for the
    user. The assembly code re-validates everything, so they can never be the last line
    of defence.
  * All DLL calls happen on the Tk main thread (the asm table is not thread-safe).

SCREENS
  AuthScreen       Log in / Sign up tabs, username + PIN fields, on-screen keypad
  LoaderScreen     progress screen after a successful log in / sign up
  DashboardScreen  balance, amount field, quick amounts, Deposit / Withdraw, receipt, keypad

RESPONSIVE BEHAVIOUR
  * Every card and keypad key stretches with the window (grid weights).
  * All fonts scale with the window size (FontBook.rescale).
  * Wide window   -> form and keypad side by side.
    Narrow window -> keypad moves underneath (apply_layout of each screen).

Run:  uv run app.py
"""
import math
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import messagebox


# ===========================================================================
#  Start-up: import the back end, and explain problems in a message box
#  (a double-clicked GUI program has no console to print errors to).
# ===========================================================================
def show_fatal_error(title_text, message_text):
    """Show a start-up problem in a message box and on stderr."""
    print(message_text, file=sys.stderr)
    try:
        hidden_root_window = tk.Tk()
        hidden_root_window.withdraw()
        messagebox.showerror(title_text, message_text)
        hidden_root_window.destroy()
    except tk.TclError:
        pass                                          # no display available: stderr is enough


try:
    import customtkinter as ctk
except ImportError:
    show_fatal_error("AsmBank ATM cannot start",
                     "The 'customtkinter' package is missing.\nInstall it with:  uv add customtkinter")
    raise SystemExit(1)

try:
    import bridge       # loads Assembly.dll (exits with a readable message if that is impossible)
    import messages     # status code -> sentence
    import storage      # users.csv <-> asm table
except SystemExit as backend_error:
    show_fatal_error("AsmBank ATM cannot start", str(backend_error))
    raise


# ===========================================================================
#  Settings
# ===========================================================================
APPLICATION_TITLE = "AsmBank ATM"

# Window size in "logical" pixels (customtkinter multiplies by the Windows display scaling).
WINDOW_DEFAULT_WIDTH = 1100
WINDOW_DEFAULT_HEIGHT = 780
WINDOW_MINIMUM_WIDTH = 1100
WINDOW_MINIMUM_HEIGHT = 780
WIDE_LAYOUT_MINIMUM_WIDTH = 900        # narrower than this -> the keypad moves below the form
REFERENCE_WIDTH = 1040                 # window size at which the fonts have their base size
REFERENCE_HEIGHT = 720
FONT_SCALE_MINIMUM = 0.85
FONT_SCALE_MAXIMUM = 1.60
RESIZE_DEBOUNCE_MILLISECONDS = 80      # wait until the user stops dragging before re-laying out

# Typing helpers (UX only - asm validates again).
USERNAME_MAX_LENGTH = 15               # NAME_LEN - 1 in main.asm
PIN_LENGTH = 4                         # PIN_LENGTH in main.asm
AMOUNT_MAX_DIGITS = 9                  # MAX_AMOUNT_DIGITS in main.asm
QUICK_AMOUNTS = (500, 1000, 5000, 10000)

# Session safety (documentation 14.4).
INACTIVITY_TIMEOUT_SECONDS = 60
INACTIVITY_WARNING_SECONDS = 15        # the countdown turns orange during the last 15 seconds
INACTIVITY_CHECK_MILLISECONDS = 250    # how often the idle clock is checked

# Loader screen timing. Every stage is (end percent, seconds it takes).
LOADER_STAGES = ((25, 0.15),           # stage 1:   0 ->  25 %
                 (65, 0.27),           # stage 2:  25 ->  65 %
                 (90, 0.17),           # stage 3:  65 ->  90 %
                 (100, 0.13))          # stage 4:  90 -> 100 %
LOADER_HOLD_SECONDS = 0.08             # short rest at 100 % before the next screen appears
LOADER_TOTAL_SECONDS = round(sum(seconds for _percent, seconds in LOADER_STAGES) + LOADER_HOLD_SECONDS, 3)
LOADER_FRAME_MILLISECONDS = 16         # about 60 animation frames per second
LOADER_BAR_WIDTH = 420

# Look and feel.
CARD_CORNER_RADIUS = 16
CONTROL_CORNER_RADIUS = 12
ENTRY_HEIGHT = 46
KEY_MINIMUM_WIDTH = 60
KEY_MINIMUM_HEIGHT = 40
STATUS_WRAP_LENGTH = 420
MASK_CHARACTER = "\u2022"              # the dot shown instead of PIN digits
SHADOW_OFFSET = 3                      # thickness of the receipt box shadow (pixels)

KEY_BACKSPACE = "\u232b"
KEY_CLEAR = "Clear"
KEYPAD_LAYOUT = (("1", "2", "3"),
                 ("4", "5", "6"),
                 ("7", "8", "9"),
                 (KEY_CLEAR, "0", KEY_BACKSPACE))

SCREEN_AUTH = "auth"
SCREEN_LOADER = "loader"
SCREEN_DASHBOARD = "dashboard"
MAXIMUM_GRID_TRACKS = 4                # rows/columns whose weights set_grid_weights() resets

CHARACTERS_DIGITS = "digits"
CHARACTERS_LETTERS_AND_DIGITS = "letters_and_digits"

TRANSACTION_DEPOSIT = "deposit"        # kinds understood by messages.transaction_title_msg
TRANSACTION_WITHDRAWAL = "withdrawal"


class Colors:
    """One palette for the whole program: ink-blue surfaces with a banknote-gold accent."""
    WINDOW_BACKGROUND = "#0B1722"
    HEADER_BACKGROUND = "#0E1F31"
    CARD_BACKGROUND = "#12263A"
    FIELD_BACKGROUND = "#0B1722"
    FIELD_BORDER = "#2A4660"
    FIELD_BORDER_KEYPAD_TARGET = "#5B84A8"     # field the keypad types into (not focused)
    KEY_BACKGROUND = "#1B3550"
    KEY_HOVER = "#27496B"
    SECONDARY_BACKGROUND = "#23415E"
    SECONDARY_HOVER = "#2D5379"
    ACCENT = "#E9B949"                         # gold: primary buttons, balance, focus ring
    ACCENT_HOVER = "#F6CB62"
    TEXT_ON_ACCENT = "#1A1405"
    TEXT_PRIMARY = "#E6EDF3"
    TEXT_MUTED = "#8FA5B8"
    SUCCESS = "#5FD3A4"
    ERROR = "#FF8A8A"
    WARNING = "#FFC46B"
    HINT_SURFACE = "#0F2132"                   # receipt box background
    HINT_SHADOW = "#091521"                    # darker frame that imitates its shadow


# ===========================================================================
#  Small pure helpers (no widgets, easy to test)
# ===========================================================================
def clamp(value, lowest, highest):
    """Keep `value` inside the range lowest..highest."""
    return max(lowest, min(highest, value))


def is_text_allowed(proposed_text, allowed_characters, maximum_length):
    """Decide whether the text a user is about to create inside an entry box is allowed.

    Used by Tk's `validatecommand`, so letters/symbols never even appear in the box.
    `isascii()` matters: str.isdigit() would also accept digits of other scripts.
    """
    if len(proposed_text) > maximum_length:
        return False
    if proposed_text == "":
        return True                                   # emptying the box is always allowed
    if not proposed_text.isascii():
        return False
    if allowed_characters == CHARACTERS_DIGITS:
        return proposed_text.isdigit()
    return proposed_text.isalnum()                    # letters and digits


def set_grid_weights(container, column_weights, row_weights, uniform_group=None):
    """Set the stretch weight of the first grid columns/rows (all others become 0).

    Stretching columns that share a `uniform_group` get sizes exactly proportional to
    their weights, whatever their content is. This keeps the Log in and Sign up cards
    the same width.
    """
    for track_index in range(MAXIMUM_GRID_TRACKS):
        column_weight = column_weights[track_index] if track_index < len(column_weights) else 0
        row_weight = row_weights[track_index] if track_index < len(row_weights) else 0
        column_uniform_group = uniform_group if (uniform_group and column_weight > 0) else ""
        container.grid_columnconfigure(track_index, weight=column_weight, uniform=column_uniform_group)
        container.grid_rowconfigure(track_index, weight=row_weight)


def wrap_text_to_width(label, container, side_padding=0):
    """Re-wrap `label` to the width of `container`, so the text ends where the button above ends."""
    def update_wrap(event):
        try:
            scaling = ctk.ScalingTracker.get_widget_scaling(label)
        except Exception:
            scaling = 1.0
        new_wrap = max(100, int(event.width / scaling) - side_padding)
        if new_wrap != getattr(label, "current_wrap", None):     # avoid pointless redraws
            label.current_wrap = new_wrap
            label.configure(wraplength=new_wrap)
    container.bind("<Configure>", update_wrap, add="+")


def choose_font_family(root_window):
    """Prefer Bahnschrift (clear, signage-like digits on Windows 10/11), else Segoe UI."""
    installed_families = set(tkfont.families(root_window))
    for family_name in ("Bahnschrift", "Segoe UI", "Helvetica Neue", "Arial"):
        if family_name in installed_families:
            return family_name
    return None                                       # None = the system default font


# ---------------------------------------------------------------------------
# Loader animation maths (pure functions, no widgets)
# ---------------------------------------------------------------------------
def ease_in_out(fraction):
    """Smooth S-curve: slow start, fast middle, slow end. 0..1 in, 0..1 out."""
    fraction = clamp(fraction, 0.0, 1.0)
    return fraction * fraction * (3.0 - 2.0 * fraction)


def loader_progress_percent(elapsed_seconds):
    """Progress (0..100) of the loader after `elapsed_seconds`.

    The bar moves stage by stage (0->25, 25->65, 65->90, 90->100); inside a stage the
    movement is eased, so the animation looks smooth and every stage visibly "lands".
    """
    stage_start_seconds = 0.0
    stage_start_percent = 0.0
    for stage_end_percent, stage_duration_seconds in LOADER_STAGES:
        stage_end_seconds = stage_start_seconds + stage_duration_seconds
        if elapsed_seconds < stage_end_seconds:
            fraction_of_stage = (elapsed_seconds - stage_start_seconds) / stage_duration_seconds
            return stage_start_percent + (stage_end_percent - stage_start_percent) * ease_in_out(fraction_of_stage)
        stage_start_seconds = stage_end_seconds
        stage_start_percent = stage_end_percent
    return 100.0                                      # finished (also during the short rest at 100 %)


def loader_stage_index(percent):
    """0..3: which of the four stages the bar is in (selects the small text under the bar)."""
    for stage_index, (stage_end_percent, _seconds) in enumerate(LOADER_STAGES):
        if percent < stage_end_percent:
            return stage_index
    return len(LOADER_STAGES) - 1


# ---------------------------------------------------------------------------
# Auto log out maths
# ---------------------------------------------------------------------------
def seconds_left_until_auto_logout(idle_seconds):
    """Seconds (never negative) that remain before the inactivity log out."""
    return max(0.0, INACTIVITY_TIMEOUT_SECONDS - idle_seconds)


class FontBook:
    """All fonts of the program. rescale() resizes them, and every widget follows."""
    # role -> (base size, weight)
    DEFINITIONS = {
        "brand":       (22, "bold"),
        "title":       (28, "bold"),
        "heading":     (18, "bold"),
        "body":        (14, "normal"),
        "small":       (12, "normal"),
        "field_label": (13, "normal"),
        "entry":       (17, "normal"),
        "button":      (15, "bold"),
        "status":      (14, "normal"),
        "balance":     (48, "bold"),
        "key_digit":   (26, "normal"),
        "key_action":  (15, "bold"),
    }

    def __init__(self, family_name):
        self.fonts = {role: ctk.CTkFont(family=family_name, size=base_size, weight=weight)
                      for role, (base_size, weight) in self.DEFINITIONS.items()}

    def __getitem__(self, role):
        return self.fonts[role]

    def rescale(self, scale_factor):
        """Resize every font to base size * scale_factor."""
        for role, (base_size, _weight) in self.DEFINITIONS.items():
            self.fonts[role].configure(size=max(8, round(base_size * scale_factor)))


# ===========================================================================
#  Reusable widgets
# ===========================================================================
class InputField(ctk.CTkFrame):
    """A caption plus an entry box that only accepts the allowed characters.

    * `allowed_characters` = digits only, or letters and digits.
    * `maximum_length` characters at most.
    * Typing, pasting and the on-screen keypad all pass through the same filter.
    """

    def __init__(self, master, fonts, caption_text, allowed_characters, maximum_length,
                 keypad_name, is_masked=False):
        super().__init__(master, fg_color="transparent")
        self.allowed_characters = allowed_characters
        self.maximum_length = maximum_length
        self.keypad_name = keypad_name                # shown on the keypad: "Typing into: PIN"
        self.has_keyboard_focus = False
        self.is_keypad_target = False

        self.grid_columnconfigure(0, weight=1)
        self.caption_label = ctk.CTkLabel(self, text=caption_text, font=fonts["field_label"],
                                          text_color=Colors.TEXT_MUTED, anchor="w")
        self.caption_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        # Tk calls this command before EVERY change of the text; returning False rejects it.
        validation_command_name = self.register(self.is_proposed_text_allowed)
        extra_entry_options = {"show": MASK_CHARACTER} if is_masked else {}
        self.entry = ctk.CTkEntry(self, height=ENTRY_HEIGHT, font=fonts["entry"],
                                  corner_radius=CONTROL_CORNER_RADIUS, border_width=2,
                                  fg_color=Colors.FIELD_BACKGROUND,
                                  border_color=Colors.FIELD_BORDER,
                                  text_color=Colors.TEXT_PRIMARY,
                                  validate="key",
                                  validatecommand=(validation_command_name, "%P"),
                                  **extra_entry_options)
        self.entry.grid(row=1, column=0, sticky="ew")
        self.entry.bind("<FocusIn>", self.on_focus_in)
        self.entry.bind("<FocusOut>", self.on_focus_out)

    # ---- filtering -------------------------------------------------------
    def is_proposed_text_allowed(self, proposed_text):
        """%P = the text the box would contain if the change were accepted."""
        return is_text_allowed(proposed_text, self.allowed_characters, self.maximum_length)

    # ---- reading and editing the text ------------------------------------
    def get(self):
        """The raw text exactly as typed (bridge.py trims it, asm judges it)."""
        return self.entry.get()

    def set_text(self, new_text):
        """Replace the whole text (the filter still applies)."""
        self.entry.delete(0, "end")
        self.entry.insert(0, new_text)

    def clear(self):
        self.entry.delete(0, "end")

    def append_character(self, character):
        """Add one character at the end. Returns False if the filter refused it."""
        current_text = self.entry.get()
        if not is_text_allowed(current_text + character, self.allowed_characters, self.maximum_length):
            return False
        self.entry.insert("end", character)
        return True

    def delete_last_character(self):
        current_text = self.entry.get()
        if current_text:
            self.entry.delete(len(current_text) - 1, "end")

    def set_masked(self, is_masked):
        """Show dots (True) or the real characters (False)."""
        self.entry.configure(show=MASK_CHARACTER if is_masked else "")

    def focus(self):
        self.entry.focus_set()

    # ---- border colour: gold = typing here, steel blue = keypad target ------
    def on_focus_in(self, _event):
        self.has_keyboard_focus = True
        self.refresh_border()

    def on_focus_out(self, _event):
        self.has_keyboard_focus = False
        self.refresh_border()

    def set_keypad_target(self, is_target):
        self.is_keypad_target = is_target
        self.refresh_border()

    def refresh_border(self):
        if self.has_keyboard_focus:
            border_color = Colors.ACCENT
        elif self.is_keypad_target:
            border_color = Colors.FIELD_BORDER_KEYPAD_TARGET
        else:
            border_color = Colors.FIELD_BORDER
        self.entry.configure(border_color=border_color)


class KeypadCard(ctk.CTkFrame):
    """On-screen numeric keypad: 1-9, Clear, 0, Backspace.

    It types into its *target field* - the number field (PIN or amount) the user
    touched last. All keys stretch with the card, so it grows with the window.
    """

    def __init__(self, master, fonts, activity_callback):
        super().__init__(master, fg_color=Colors.CARD_BACKGROUND, corner_radius=CARD_CORNER_RADIUS)
        self.fonts = fonts
        self.activity_callback = activity_callback    # tells the inactivity timer "someone is here"
        self.target_field = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)           # the keys take all spare height

        self.title_label = ctk.CTkLabel(self, text="Keypad", font=fonts["heading"],
                                        text_color=Colors.TEXT_PRIMARY, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        self.target_label = ctk.CTkLabel(self, text="Tap a number field first", font=fonts["small"],
                                         text_color=Colors.TEXT_MUTED, anchor="w")
        self.target_label.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))

        keys_frame = ctk.CTkFrame(self, fg_color="transparent")
        keys_frame.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        for row_index, row_keys in enumerate(KEYPAD_LAYOUT):
            keys_frame.grid_rowconfigure(row_index, weight=1, uniform="keypad_rows")
            for column_index, key_label in enumerate(row_keys):
                keys_frame.grid_columnconfigure(column_index, weight=1, uniform="keypad_columns")
                self.create_key(keys_frame, key_label).grid(row=row_index, column=column_index,
                                                            sticky="nsew", padx=4, pady=4)

    def create_key(self, parent, key_label):
        """One key button. Digits are the dark keys, Clear/Backspace are the lighter ones."""
        is_digit_key = key_label.isdigit()
        return ctk.CTkButton(
            parent, text=key_label, width=KEY_MINIMUM_WIDTH, height=KEY_MINIMUM_HEIGHT,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=self.fonts["key_digit"] if is_digit_key else self.fonts["key_action"],
            fg_color=Colors.KEY_BACKGROUND if is_digit_key else Colors.SECONDARY_BACKGROUND,
            hover_color=Colors.KEY_HOVER if is_digit_key else Colors.SECONDARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            command=lambda pressed_key=key_label: self.on_key_pressed(pressed_key))

    # ---- choosing where the keys type ------------------------------------
    def watch(self, field):
        """Make `field` the keypad target whenever the user clicks into it."""
        field.entry.bind("<FocusIn>", lambda _event, watched_field=field: self.set_target(watched_field))

    def set_target(self, field):
        if self.target_field is not None and self.target_field is not field:
            self.target_field.set_keypad_target(False)
        self.target_field = field
        field.set_keypad_target(True)
        self.target_label.configure(text=f"Typing into: {field.keypad_name}")

    # ---- key actions -----------------------------------------------------
    def on_key_pressed(self, key_label):
        self.activity_callback()
        if self.target_field is None:
            self.bell()
        elif key_label.isdigit():
            if not self.target_field.append_character(key_label):
                self.bell()                           # field is full (or refused the character)
        elif key_label == KEY_CLEAR:
            self.target_field.clear()
        elif key_label == KEY_BACKSPACE:
            self.target_field.delete_last_character()


class ShadowBox(ctk.CTkFrame):
    """A rounded surface with a shadow-colored border. Put your widgets into `surface`."""

    def __init__(self, master, surface_color, shadow_color, corner_radius=CONTROL_CORNER_RADIUS):
        super().__init__(master, fg_color="transparent", corner_radius=corner_radius)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.surface = ctk.CTkFrame(self, fg_color=surface_color, corner_radius=corner_radius,
                                    border_width=SHADOW_OFFSET, border_color=shadow_color)
        self.surface.grid(row=0, column=0, sticky="nsew")
        self.surface.grid_columnconfigure(0, weight=1)


# ===========================================================================
#  Screen 1: Log in / Sign up
# ===========================================================================
class AuthScreen(ctk.CTkFrame):
    """Welcome screen with two tabs (Log in, Sign up) sharing one form."""

    MODE_LOG_IN = "Log in"
    MODE_SIGN_UP = "Sign up"
    # mode -> (heading, hint under the heading, label of the main button)
    MODE_TEXTS = {
        MODE_LOG_IN:  ("Welcome back", "Enter your username and PIN.", "Log in"),
        MODE_SIGN_UP: ("Create an account", "Choose a username and a 4-digit PIN.", "Create account"),
    }

    def __init__(self, master, application):
        super().__init__(master, fg_color="transparent")
        self.application = application
        fonts = application.fonts
        self.current_mode = self.MODE_LOG_IN

        # ---- the form card -------------------------------------------------
        self.form_card = ctk.CTkFrame(self, fg_color=Colors.CARD_BACKGROUND,
                                      corner_radius=CARD_CORNER_RADIUS)
        self.form_card.grid_columnconfigure(0, weight=1)
        self.form_card.grid_rowconfigure(0, weight=1)         # spacer above  } keeps the form
        self.form_card.grid_rowconfigure(2, weight=1)         # spacer below  } vertically centred
        form_content = ctk.CTkFrame(self.form_card, fg_color="transparent")
        form_content.grid(row=1, column=0, sticky="ew", padx=32, pady=16)
        form_content.grid_columnconfigure(0, weight=1)

        self.mode_switch = ctk.CTkSegmentedButton(
            form_content, values=[self.MODE_LOG_IN, self.MODE_SIGN_UP], command=self.switch_mode,
            font=fonts["button"], height=40, corner_radius=CONTROL_CORNER_RADIUS,
            fg_color=Colors.FIELD_BACKGROUND,
            selected_color=Colors.ACCENT, selected_hover_color=Colors.ACCENT_HOVER,
            unselected_color=Colors.FIELD_BACKGROUND, unselected_hover_color=Colors.KEY_BACKGROUND,
            text_color=Colors.TEXT_PRIMARY)
        self.mode_switch.set(self.MODE_LOG_IN)
        self.mode_switch.grid(row=0, column=0, sticky="ew")

        self.heading_label = ctk.CTkLabel(form_content, text="", font=fonts["title"],
                                          text_color=Colors.TEXT_PRIMARY, anchor="w")
        self.heading_label.grid(row=1, column=0, sticky="ew", pady=(20, 0))
        self.hint_label = ctk.CTkLabel(form_content, text="", font=fonts["body"],
                                       text_color=Colors.TEXT_MUTED, anchor="w", justify="left",
                                       wraplength=STATUS_WRAP_LENGTH)
        self.hint_label.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        wrap_text_to_width(self.hint_label, form_content)

        self.username_field = InputField(form_content, fonts, "Username",
                                         CHARACTERS_LETTERS_AND_DIGITS, USERNAME_MAX_LENGTH,
                                         keypad_name="Username")
        self.username_field.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.pin_field = InputField(form_content, fonts, "PIN", CHARACTERS_DIGITS, PIN_LENGTH,
                                    keypad_name="PIN", is_masked=True)
        self.pin_field.grid(row=4, column=0, sticky="ew", pady=(12, 0))

        self.show_pin_switch = ctk.CTkSwitch(form_content, text="Show PIN", font=fonts["small"],
                                             text_color=Colors.TEXT_MUTED,
                                             progress_color=Colors.ACCENT,
                                             command=self.on_show_pin_toggled)
        self.show_pin_switch.grid(row=5, column=0, sticky="w", pady=(10, 0))

        self.submit_button = ctk.CTkButton(form_content, text="", height=48, font=fonts["button"],
                                           corner_radius=CONTROL_CORNER_RADIUS,
                                           fg_color=Colors.ACCENT, hover_color=Colors.ACCENT_HOVER,
                                           text_color=Colors.TEXT_ON_ACCENT, command=self.submit)
        self.submit_button.grid(row=6, column=0, sticky="ew", pady=(14, 0))

        self.status_label = ctk.CTkLabel(form_content, text="", font=fonts["status"], anchor="w",
                                         justify="left", wraplength=STATUS_WRAP_LENGTH,
                                         text_color=Colors.TEXT_MUTED)
        self.status_label.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        wrap_text_to_width(self.status_label, form_content)

        # Pressing Enter on the keyboard does the same as the main button.
        self.username_field.entry.bind("<Return>", lambda _event: self.submit())
        self.pin_field.entry.bind("<Return>", lambda _event: self.submit())

        # ---- the keypad card (types into the PIN field) ------------------------
        self.keypad_card = KeypadCard(self, fonts, application.note_activity)
        self.keypad_card.watch(self.pin_field)
        self.keypad_card.set_target(self.pin_field)

        self.apply_texts_for_mode()
        self.apply_layout(is_wide=True)

    # ---- layout ----------------------------------------------------------------
    def apply_layout(self, is_wide):
        """Wide window: form | keypad.  Narrow window: form above keypad."""
        self.form_card.grid_forget()
        self.keypad_card.grid_forget()
        if is_wide:
            # The form column is always exactly 3/5 of the width, in Log in AND Sign up mode.
            set_grid_weights(self, column_weights=(3, 2), row_weights=(1,), uniform_group="auth_columns")
            self.form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.keypad_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        else:
            set_grid_weights(self, column_weights=(1,), row_weights=(3, 2))
            self.form_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
            self.keypad_card.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # ---- mode (tab) handling ---------------------------------------------------
    def apply_texts_for_mode(self):
        heading_text, hint_text, button_text = self.MODE_TEXTS[self.current_mode]
        self.heading_label.configure(text=heading_text)
        self.hint_label.configure(text=hint_text)
        self.submit_button.configure(text=button_text)

    def switch_mode(self, new_mode):
        """Called by the tab control (and by the code after a successful sign-up)."""
        self.application.note_activity()
        self.current_mode = new_mode
        self.mode_switch.set(new_mode)
        self.apply_texts_for_mode()
        self.pin_field.clear()                        # a PIN never survives a tab change
        self.show_status("", Colors.TEXT_MUTED)

    def on_show_pin_toggled(self):
        self.pin_field.set_masked(not self.show_pin_switch.get())

    # ---- helpers ---------------------------------------------------------------
    def show_status(self, status_text, status_color):
        self.status_label.configure(text=status_text, text_color=status_color)

    def reset(self, notice_text="", notice_color=Colors.TEXT_MUTED):
        """Return to a clean Log in form (after logout / inactivity timeout)."""
        self.current_mode = self.MODE_LOG_IN
        self.mode_switch.set(self.MODE_LOG_IN)
        self.apply_texts_for_mode()
        self.username_field.clear()
        self.pin_field.clear()
        self.show_pin_switch.deselect()
        self.pin_field.set_masked(True)
        self.keypad_card.set_target(self.pin_field)
        self.show_status(notice_text, notice_color)
        self.username_field.focus()

    # ---- the two actions -------------------------------------------------------
    def submit(self):
        # Ignore Enter / clicks while another screen (the loader) is showing, otherwise a
        # second log in could start behind the loader.
        if self.application.active_screen_name != SCREEN_AUTH:
            return
        self.application.note_activity()
        if self.current_mode == self.MODE_LOG_IN:
            self.handle_log_in()
        else:
            self.handle_sign_up()

    def handle_log_in(self):
        user_name = self.username_field.get()
        result_code = bridge.login(user_name, self.pin_field.get())   # asm does ALL the checking
        status_text = messages.login_msg(result_code, user_name)
        self.pin_field.clear()                                        # never leave a PIN on screen

        # Documentation 10.5: success, wrong PIN and lock all changed data, so save them.
        save_failed = False
        if result_code in (1, 0, -2):
            save_failed = not storage.save_users()

        if result_code == 1:
            notice_text = messages.save_failed_msg() if save_failed else ""
            self.application.begin_session(user_name.strip(), notice_text)
        else:
            if save_failed:
                status_text += "\n" + messages.save_failed_msg()
            self.show_status(status_text, Colors.ERROR)

    def handle_sign_up(self):
        result_code = bridge.sign_up(self.username_field.get(), self.pin_field.get())
        status_text = messages.signup_msg(result_code)
        if result_code == 1:
            saved = storage.save_users()
            self.pin_field.clear()
            if saved:
                self.application.begin_sign_up_loader(status_text, Colors.SUCCESS)
            else:
                self.application.begin_sign_up_loader(status_text + "\n" + messages.save_failed_msg(),
                                                      Colors.WARNING)
        else:
            self.pin_field.clear()
            self.show_status(status_text, Colors.ERROR)


# ===========================================================================
#  Screen 2: Loader (whole window, short fixed duration)
# ===========================================================================
class LoaderScreen(ctk.CTkFrame):
    """A full-window progress screen shown after a correct log in / sign up.

    * Always takes LOADER_TOTAL_SECONDS: the progress is calculated from the real
      clock, not from the number of frames, so a slow computer shows fewer frames but
      finishes at the same moment.
    * The bar moves 0->25 %, 25->65 %, 65->90 %, 90->100 % with smooth easing.
    """

    def __init__(self, master, application):
        super().__init__(master, fg_color="transparent")
        self.application = application
        fonts = application.fonts
        self.animation_job = None               # pending after() call of the animation loop
        self.start_time = 0.0                   # clock value when the loader started
        self.stage_texts = ("", "", "", "")     # one small text per stage
        self.on_finished = None                 # function that shows the next screen

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # No "sticky": the card keeps its natural size and stays centred in the window.
        self.loader_card = ctk.CTkFrame(self, fg_color=Colors.CARD_BACKGROUND,
                                        corner_radius=CARD_CORNER_RADIUS)
        self.loader_card.grid(row=0, column=0)
        self.loader_card.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(self.loader_card, text="", font=fonts["title"],
                                        text_color=Colors.TEXT_PRIMARY)
        self.title_label.grid(row=0, column=0, padx=56, pady=(40, 0))
        self.percent_label = ctk.CTkLabel(self.loader_card, text="0%", font=fonts["balance"],
                                          text_color=Colors.ACCENT)
        self.percent_label.grid(row=1, column=0, padx=56, pady=(14, 0))
        self.progress_bar = ctk.CTkProgressBar(self.loader_card, width=LOADER_BAR_WIDTH, height=14,
                                               corner_radius=7, fg_color=Colors.FIELD_BACKGROUND,
                                               progress_color=Colors.ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, padx=56, pady=(10, 0), sticky="ew")
        self.stage_label = ctk.CTkLabel(self.loader_card, text="", font=fonts["body"],
                                        text_color=Colors.TEXT_MUTED)
        self.stage_label.grid(row=3, column=0, padx=56, pady=(14, 40))

    def apply_layout(self, _is_wide):
        """The loader looks the same in wide and narrow windows (it is centred)."""

    def start(self, title_text, stage_texts, on_finished):
        """Begin the animation; `on_finished()` is called once, exactly LOADER_TOTAL_SECONDS later."""
        self.cancel()
        self.title_label.configure(text=title_text)
        self.stage_texts = stage_texts
        self.on_finished = on_finished
        self.start_time = time.monotonic()
        self.render(0.0)
        self.animation_job = self.after(LOADER_FRAME_MILLISECONDS, self.animate)

    def animate(self):
        """One animation frame: read the clock, draw the bar, schedule the next frame."""
        self.animation_job = None
        elapsed_seconds = time.monotonic() - self.start_time
        self.render(loader_progress_percent(elapsed_seconds))
        if elapsed_seconds >= LOADER_TOTAL_SECONDS:
            finished_callback, self.on_finished = self.on_finished, None
            if finished_callback is not None:
                finished_callback()                 # switch to the next screen
        else:
            self.animation_job = self.after(LOADER_FRAME_MILLISECONDS, self.animate)

    def render(self, percent):
        """Draw the bar, the percentage and the text of the current stage."""
        self.progress_bar.set(percent / 100.0)
        self.percent_label.configure(text=f"{int(percent)}%")
        stage_index = min(loader_stage_index(percent), len(self.stage_texts) - 1)
        self.stage_label.configure(text=self.stage_texts[stage_index] if self.stage_texts else "")

    def cancel(self):
        """Stop the animation (used when the window closes)."""
        if self.animation_job is not None:
            self.after_cancel(self.animation_job)
            self.animation_job = None
        self.on_finished = None


# ===========================================================================
#  Screen 3: Dashboard (balance, deposit, withdraw)
# ===========================================================================
class DashboardScreen(ctk.CTkFrame):
    """Shown after a successful login."""

    def __init__(self, master, application):
        super().__init__(master, fg_color="transparent")
        self.application = application
        fonts = application.fonts

        # The left column holds greeting + balance + transaction cards.
        self.left_column = ctk.CTkFrame(self, fg_color="transparent")
        self.left_column.grid_columnconfigure(0, weight=1)
        self.left_column.grid_rowconfigure(2, weight=1)

        self.welcome_label = ctk.CTkLabel(self.left_column, text="", font=fonts["title"],
                                          text_color=Colors.TEXT_PRIMARY, anchor="w")
        self.welcome_label.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # ---- balance card ------------------------------------------------------
        self.balance_card = ctk.CTkFrame(self.left_column, fg_color=Colors.CARD_BACKGROUND,
                                         corner_radius=CARD_CORNER_RADIUS)
        self.balance_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.balance_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.balance_card, text="Available balance", font=fonts["body"],
                     text_color=Colors.TEXT_MUTED, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=24, pady=(16, 0))
        self.balance_label = ctk.CTkLabel(self.balance_card, text=messages.format_rupees(0),
                                          font=fonts["balance"], text_color=Colors.ACCENT, anchor="w")
        self.balance_label.grid(row=1, column=0, sticky="ew", padx=24)
        self.limits_label = ctk.CTkLabel(self.balance_card, text=messages.limits_text(),
                                         font=fonts["small"], text_color=Colors.TEXT_MUTED,
                                         anchor="w", justify="left")
        self.limits_label.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 16))

        # ---- transaction card --------------------------------------------------
        self.transaction_card = ctk.CTkFrame(self.left_column, fg_color=Colors.CARD_BACKGROUND,
                                             corner_radius=CARD_CORNER_RADIUS)
        self.transaction_card.grid(row=2, column=0, sticky="nsew")
        self.transaction_card.grid_columnconfigure(0, weight=1)
        self.transaction_card.grid_rowconfigure(0, weight=1)    # spacers keep the controls
        self.transaction_card.grid_rowconfigure(2, weight=1)    # vertically centred
        transaction_content = ctk.CTkFrame(self.transaction_card, fg_color="transparent")
        transaction_content.grid(row=1, column=0, sticky="ew", padx=24, pady=14)
        transaction_content.grid_columnconfigure(0, weight=1)

        self.amount_field = InputField(transaction_content, fonts, "Amount (Rs)", CHARACTERS_DIGITS,
                                       AMOUNT_MAX_DIGITS, keypad_name="Amount")
        self.amount_field.grid(row=0, column=0, sticky="ew")

        quick_amounts_frame = ctk.CTkFrame(transaction_content, fg_color="transparent")
        quick_amounts_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for column_index, quick_amount in enumerate(QUICK_AMOUNTS):
            quick_amounts_frame.grid_columnconfigure(column_index, weight=1, uniform="quick_amounts")
            ctk.CTkButton(quick_amounts_frame, text=f"{quick_amount:,}", height=38,
                          font=fonts["button"], corner_radius=CONTROL_CORNER_RADIUS,
                          fg_color=Colors.KEY_BACKGROUND, hover_color=Colors.KEY_HOVER,
                          text_color=Colors.TEXT_PRIMARY,
                          command=lambda chosen_amount=quick_amount: self.fill_quick_amount(chosen_amount)
                          ).grid(row=0, column=column_index, sticky="ew", padx=3)

        action_buttons_frame = ctk.CTkFrame(transaction_content, fg_color="transparent")
        action_buttons_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        action_buttons_frame.grid_columnconfigure((0, 1), weight=1, uniform="action_buttons")
        self.deposit_button = ctk.CTkButton(action_buttons_frame, text="Deposit", height=48,
                                            font=fonts["button"], corner_radius=CONTROL_CORNER_RADIUS,
                                            fg_color=Colors.SECONDARY_BACKGROUND,
                                            hover_color=Colors.SECONDARY_HOVER,
                                            text_color=Colors.TEXT_PRIMARY, command=self.handle_deposit)
        self.deposit_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.withdraw_button = ctk.CTkButton(action_buttons_frame, text="Withdraw", height=48,
                                             font=fonts["button"], corner_radius=CONTROL_CORNER_RADIUS,
                                             fg_color=Colors.ACCENT, hover_color=Colors.ACCENT_HOVER,
                                             text_color=Colors.TEXT_ON_ACCENT,
                                             command=self.handle_withdraw)
        self.withdraw_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.status_label = ctk.CTkLabel(transaction_content, text="", font=fonts["status"],
                                         anchor="w", justify="left", wraplength=STATUS_WRAP_LENGTH,
                                         text_color=Colors.TEXT_MUTED)
        self.status_label.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        wrap_text_to_width(self.status_label, transaction_content)

        # ---- receipt box ---------------------------------------------------------
        # Shown only after a successful deposit/withdraw. The success message stays outside
        # (above); the transaction details and the "view the AsmBank app" hint are inside.
        self.receipt_box = ShadowBox(transaction_content, Colors.HINT_SURFACE, Colors.HINT_SHADOW)
        self.receipt_box.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        receipt_surface = self.receipt_box.surface

        self.receipt_title_label = ctk.CTkLabel(receipt_surface, text="", font=fonts["button"],
                                                text_color=Colors.TEXT_PRIMARY, anchor="w")
        self.receipt_title_label.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        self.receipt_details_label = ctk.CTkLabel(receipt_surface, text="", font=fonts["small"],
                                                  text_color=Colors.TEXT_MUTED, anchor="w",
                                                  justify="left", wraplength=STATUS_WRAP_LENGTH)
        self.receipt_details_label.grid(row=1, column=0, sticky="ew", padx=14)
        wrap_text_to_width(self.receipt_details_label, receipt_surface, side_padding=34)
        receipt_divider = ctk.CTkFrame(receipt_surface, height=1, corner_radius=0,
                                       fg_color=Colors.FIELD_BORDER)
        receipt_divider.grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 0))
        self.hint_label = ctk.CTkLabel(receipt_surface, text=messages.bank_app_hint_msg(),
                                       font=fonts["small"], text_color=Colors.TEXT_MUTED, anchor="w",
                                       justify="left", wraplength=STATUS_WRAP_LENGTH)
        self.hint_label.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 12))
        wrap_text_to_width(self.hint_label, receipt_surface, side_padding=34)
        self.hide_receipt()                                     # nothing to show before the first transaction

        # ---- keypad (types into the amount field) --------------------------------
        self.keypad_card = KeypadCard(self, fonts, application.note_activity)
        self.keypad_card.watch(self.amount_field)
        self.keypad_card.set_target(self.amount_field)

        self.apply_layout(is_wide=True)

    # ---- layout ----------------------------------------------------------------
    def apply_layout(self, is_wide):
        """Wide window: cards | keypad.  Narrow window: cards above keypad."""
        self.left_column.grid_forget()
        self.keypad_card.grid_forget()
        if is_wide:
            set_grid_weights(self, column_weights=(3, 2), row_weights=(1,), uniform_group="dashboard_columns")
            self.left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.keypad_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            self.limits_label.grid()
        else:
            set_grid_weights(self, column_weights=(1,), row_weights=(3, 2))
            self.left_column.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
            self.keypad_card.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
            self.limits_label.grid_remove()           # the stacked layout is short of vertical space

    # ---- session start / end -------------------------------------------------
    def enter_session(self, user_name, notice_text=""):
        """Prepare the dashboard for a user who has just logged in."""
        self.welcome_label.configure(text=f"Welcome, {user_name}")
        self.amount_field.clear()
        self.keypad_card.set_target(self.amount_field)
        self.refresh_balance()
        self.hide_receipt()                           # no old receipt for a new session
        if notice_text:
            self.show_status(notice_text, Colors.WARNING)
        else:
            self.show_status("", Colors.TEXT_MUTED)
        self.amount_field.focus()

    def leave_session(self):
        """Wipe everything personal from the dashboard (logout / timeout)."""
        self.welcome_label.configure(text="")
        self.balance_label.configure(text=messages.format_rupees(0))
        self.amount_field.clear()
        self.hide_receipt()                           # the receipt is personal data too
        self.show_status("", Colors.TEXT_MUTED)

    def refresh_balance(self):
        """The balance always comes from asm - Python never calculates it."""
        self.balance_label.configure(text=messages.format_rupees(bridge.get_balance()))

    def show_status(self, status_text, status_color):
        self.status_label.configure(text=status_text, text_color=status_color)

    # ---- receipt helpers ------------------------------------------------------------
    def show_receipt(self, transaction_kind, amount, balance_after):
        """Fill and show the receipt box (transaction details + the app hint)."""
        moment = datetime.now()
        self.receipt_title_label.configure(text=messages.transaction_title_msg(transaction_kind, amount))
        self.receipt_details_label.configure(
            text=messages.transaction_details_msg(moment, balance_after))
        self.receipt_box.grid()                       # grid() restores a widget hidden by grid_remove()

    def hide_receipt(self):
        """Hide the receipt (after a failed attempt, logout, new session)."""
        self.receipt_box.grid_remove()

    # ---- actions -----------------------------------------------------------------
    def fill_quick_amount(self, chosen_amount):
        """Quick buttons only FILL the box; the normal asm checks still run on Deposit/Withdraw."""
        self.application.note_activity()
        self.amount_field.set_text(str(chosen_amount))

    def handle_deposit(self):
        self.application.note_activity()
        balance_before = bridge.get_balance()                         # asked from asm, not calculated
        result_code = bridge.deposit(self.amount_field.get())         # asm does ALL the checking
        self.finish_transaction(result_code, messages.deposit_msg(result_code),
                                TRANSACTION_DEPOSIT, balance_before)

    def handle_withdraw(self):
        self.application.note_activity()
        balance_before = bridge.get_balance()                         # asked from asm, not calculated
        result_code = bridge.withdraw(self.amount_field.get())        # asm does ALL the checking
        self.finish_transaction(result_code, messages.withdraw_msg(result_code),
                                TRANSACTION_WITHDRAWAL, balance_before)

    def finish_transaction(self, result_code, status_text, transaction_kind, balance_before):
        """Common ending of Deposit and Withdraw (documentation 14.3)."""
        succeeded = (result_code == 1)
        self.show_status(status_text, Colors.SUCCESS if succeeded else Colors.ERROR)
        if succeeded:
            if not storage.save_users():                               # balance changed: persist it
                self.show_status(messages.save_failed_msg(), Colors.WARNING)
            self.refresh_balance()
            # The amount is the difference between the two balances that asm reported, so
            # Python still parses and calculates nothing on its own.
            balance_after = bridge.get_balance()
            transaction_amount = abs(balance_after - balance_before)
            self.show_receipt(transaction_kind, transaction_amount, balance_after)
            self.amount_field.clear()
        else:
            self.hide_receipt()                       # a failed attempt must not show an old receipt


# ===========================================================================
#  The application window
# ===========================================================================
class AtmApplication(ctk.CTk):
    """Main window: header bar + one visible screen, session timer, responsive layout."""

    def __init__(self, skipped_row_count=0):
        super().__init__(fg_color=Colors.WINDOW_BACKGROUND)
        self.title(APPLICATION_TITLE)
        self.is_closing = False
        self.last_activity_time = time.monotonic()
        self.active_screen_name = SCREEN_AUTH
        self.is_wide_layout = None                    # unknown until the first layout pass
        self.current_font_scale = 1.0
        self.layout_job = None                        # pending "re-layout" scheduled with after()
        self.inactivity_job = None                    # pending "check the idle time" scheduled with after()
        self.countdown_text = ""                      # text currently shown in the header countdown

        self.geometry(f"{WINDOW_DEFAULT_WIDTH}x{WINDOW_DEFAULT_HEIGHT}")
        self.minsize(WINDOW_MINIMUM_WIDTH, WINDOW_MINIMUM_HEIGHT)

        self.fonts = FontBook(choose_font_family(self))

        # ---- the window is: row 0 = header, row 1 = body ------------------------------
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.build_header()
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(16, 24))
        self.body_frame.grid_columnconfigure(0, weight=1)
        self.body_frame.grid_rowconfigure(0, weight=1)

        self.screens = {SCREEN_AUTH: AuthScreen(self.body_frame, self),
                        SCREEN_LOADER: LoaderScreen(self.body_frame, self),
                        SCREEN_DASHBOARD: DashboardScreen(self.body_frame, self)}
        self.show_screen(SCREEN_AUTH)

        # ---- behaviours ---------------------------------------------------------------
        self.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.bind("<Configure>", self.on_window_resized)
        self.bind_all("<Key>", self.note_activity, add="+")            # any key press = activity
        self.bind_all("<ButtonPress>", self.note_activity, add="+")    # any click/tap = activity
        self.inactivity_job = self.after(INACTIVITY_CHECK_MILLISECONDS, self.check_inactivity)
        self.after(100, self.apply_responsive_layout)                  # first layout pass
        self.after(150, self.screens[SCREEN_AUTH].username_field.focus)

        if skipped_row_count:                                          # documentation 10.1
            self.after(400, lambda: messagebox.showwarning(
                "users.csv", messages.rejected_rows_msg(skipped_row_count), parent=self))

    # ---- header bar ---------------------------------------------------------------
    def build_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color=Colors.HEADER_BACKGROUND, corner_radius=0)
        self.header_frame.grid(row=0, column=0, sticky="ew")
        self.header_frame.grid_columnconfigure(2, weight=1)           # pushes the right side away

        ctk.CTkLabel(self.header_frame, text=APPLICATION_TITLE, font=self.fonts["brand"],
                     text_color=Colors.ACCENT).grid(row=0, column=0, padx=(24, 12), pady=14)

        self.countdown_label = ctk.CTkLabel(self.header_frame, text="", font=self.fonts["small"],
                                            text_color=Colors.WARNING)
        self.countdown_label.grid(row=0, column=3, padx=(0, 12))
        self.logout_button = ctk.CTkButton(self.header_frame, text="Log out", width=96, height=36,
                                           font=self.fonts["button"], corner_radius=CONTROL_CORNER_RADIUS,
                                           fg_color=Colors.SECONDARY_BACKGROUND,
                                           hover_color=Colors.SECONDARY_HOVER,
                                           text_color=Colors.TEXT_PRIMARY,
                                           command=self.on_logout_clicked)
        self.logout_button.grid(row=0, column=4, padx=(0, 24))
        self.logout_button.grid_remove()                              # only visible on the dashboard
        self.countdown_label.grid_remove()

    # ---- screens ----------------------------------------------------------------------
    def show_screen(self, screen_name):
        """Show one screen, hide the others, and adjust the header."""
        self.active_screen_name = screen_name
        for name, screen in self.screens.items():
            if name == screen_name:
                screen.grid(row=0, column=0, sticky="nsew")
            else:
                screen.grid_forget()
        if screen_name == SCREEN_DASHBOARD:
            self.logout_button.grid()
            self.countdown_label.grid()
            self.update_countdown_label()
        else:
            self.logout_button.grid_remove()
            self.countdown_label.grid_remove()

    def begin_session(self, user_name, notice_text=""):
        """Called by the Log in screen after asm accepted the PIN: loader first, then dashboard."""
        loader_title, stage_texts = messages.loader_texts(is_sign_up=False)

        def open_dashboard():
            """Runs when the loader reaches 100 %: this is where the session really opens."""
            self.note_activity()                       # the idle clock starts now, not before the loader
            self.screens[SCREEN_DASHBOARD].enter_session(user_name, notice_text)
            self.show_screen(SCREEN_DASHBOARD)

        self.start_loader(loader_title, stage_texts, open_dashboard)

    def begin_sign_up_loader(self, status_text, status_color):
        """Show the loader, then the Log in tab with `status_text` (account created)."""
        loader_title, stage_texts = messages.loader_texts(is_sign_up=True)
        auth_screen = self.screens[SCREEN_AUTH]

        def show_log_in_form():
            auth_screen.switch_mode(AuthScreen.MODE_LOG_IN)    # keeps the username, clears the PIN
            auth_screen.show_status(status_text, status_color)
            self.show_screen(SCREEN_AUTH)
            auth_screen.pin_field.focus()

        self.start_loader(loader_title, stage_texts, show_log_in_form)

    def start_loader(self, loader_title, stage_texts, on_finished):
        """Switch the whole window to the loader screen and start its animation."""
        self.show_screen(SCREEN_LOADER)
        self.screens[SCREEN_LOADER].start(loader_title, stage_texts, on_finished)

    def end_session(self, notice_text="", notice_color=Colors.TEXT_MUTED):
        """Logout (button or timeout): asm forgets the user, the screens are wiped."""
        bridge.logout()
        self.screens[SCREEN_DASHBOARD].leave_session()
        self.screens[SCREEN_AUTH].reset(notice_text, notice_color)
        self.show_screen(SCREEN_AUTH)

    def on_logout_clicked(self):
        self.end_session()

    # ---- inactivity timer ---------------------------------------------------------------
    def note_activity(self, _event=None):
        """Restart the idle clock (called on every key press, click and keypad tap)."""
        self.last_activity_time = time.monotonic()
        self.update_countdown_label()

    def update_countdown_label(self):
        """Show 'Auto log out in N seconds' in the header. Orange during the last 15 seconds."""
        if self.active_screen_name != SCREEN_DASHBOARD:
            return
        seconds_left = seconds_left_until_auto_logout(time.monotonic() - self.last_activity_time)
        new_text = f"Auto log out in {math.ceil(seconds_left)} seconds"
        if new_text == self.countdown_text:
            return                                    # nothing changed: save a redraw
        self.countdown_text = new_text
        text_color = Colors.WARNING if seconds_left <= INACTIVITY_WARNING_SECONDS else Colors.TEXT_MUTED
        self.countdown_label.configure(text=new_text, text_color=text_color)

    def check_inactivity(self):
        """Runs four times a second. After 60 idle seconds on the dashboard: log out."""
        if self.is_closing:
            return
        if self.active_screen_name == SCREEN_DASHBOARD:
            idle_seconds = time.monotonic() - self.last_activity_time
            if seconds_left_until_auto_logout(idle_seconds) <= 0:
                self.end_session(messages.auto_logout_msg(INACTIVITY_TIMEOUT_SECONDS), Colors.WARNING)
            else:
                self.update_countdown_label()
        self.inactivity_job = self.after(INACTIVITY_CHECK_MILLISECONDS, self.check_inactivity)

    # ---- responsive layout --------------------------------------------------------------------
    def get_display_scaling(self):
        """Windows display scaling (1.0 = 100 %, 1.5 = 150 %, ...)."""
        try:
            return float(ctk.ScalingTracker.get_window_scaling(self))
        except Exception:
            return max(self.winfo_fpixels("1i") / 96.0, 1.0)

    def on_window_resized(self, event):
        """Tk sends <Configure> for every child too; react only to the window itself."""
        if event.widget is not self:
            return
        if self.layout_job is not None:
            self.after_cancel(self.layout_job)
        self.layout_job = self.after(RESIZE_DEBOUNCE_MILLISECONDS, self.apply_responsive_layout)

    def apply_responsive_layout(self):
        """Scale the fonts to the window size and pick the wide or narrow arrangement."""
        self.layout_job = None
        if self.is_closing:
            return
        display_scaling = self.get_display_scaling()
        logical_width = self.winfo_width() / display_scaling
        logical_height = self.winfo_height() / display_scaling

        font_scale = clamp(min(logical_width / REFERENCE_WIDTH, logical_height / REFERENCE_HEIGHT),
                           FONT_SCALE_MINIMUM, FONT_SCALE_MAXIMUM)
        if abs(font_scale - self.current_font_scale) >= 0.03:          # ignore tiny changes
            self.current_font_scale = font_scale
            self.fonts.rescale(font_scale)

        is_wide = logical_width >= WIDE_LAYOUT_MINIMUM_WIDTH
        if is_wide != self.is_wide_layout:
            self.is_wide_layout = is_wide
            for screen in self.screens.values():
                screen.apply_layout(is_wide)

    # ---- closing --------------------------------------------------------------------------------
    def on_close_requested(self):
        """Window close: forget the session, save once more as a safety net, quit."""
        self.is_closing = True
        self.screens[SCREEN_LOADER].cancel()          # stop a running loader animation
        for pending_job in (self.layout_job, self.inactivity_job):
            if pending_job is not None:
                self.after_cancel(pending_job)
        bridge.logout()
        if not storage.save_users():
            messagebox.showwarning("users.csv", messages.save_failed_msg(), parent=self)
        self.destroy()


def main():
    """Load users.csv into the asm table, then open the window."""
    _loaded_count, skipped_count = storage.load_users()
    ctk.set_appearance_mode("dark")
    application = AtmApplication(skipped_row_count=skipped_count)
    application.mainloop()


if __name__ == "__main__":
    main()
