"""bridge.py - thin ctypes wrapper around Assembly.dll.

No business rules live here: this file only converts text/numbers and calls the DLL.
Every ATM rule (validation, hashing, limits, balances) is decided by the assembly code.

Run `uv run bridge.py` for a console self-test of the assembly logic.
"""
import ctypes
import struct
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. The DLL is 32-bit (MASM .model flat), so Python itself must be 32-bit too:
#    a process can only load DLLs of its own bitness.
# ---------------------------------------------------------------------------
if struct.calcsize("P") * 8 != 32:
    raise SystemExit(
        "Need 32-bit Python: Assembly.dll is x86.\n"
        "Run the project with `uv run` inside the Python folder (it pins 32-bit Python)."
    )

# ---------------------------------------------------------------------------
# 2. Locate the DLL:   ASMBank-ATM\Python\bridge.py  ->  ASMBank-ATM\Assembly\Debug\Assembly.dll
# ---------------------------------------------------------------------------
PROJECT_FOLDER = Path(__file__).resolve().parent.parent
DLL_CANDIDATE_PATHS = [
    PROJECT_FOLDER / "Assembly" / "Debug" / "Assembly.dll",      # normal Debug | x86 build
    PROJECT_FOLDER / "Assembly" / "Release" / "Assembly.dll",    # in case it was built as Release
]
DLL_PATH = next((path for path in DLL_CANDIDATE_PATHS if path.exists()), None)
if DLL_PATH is None:
    raise SystemExit(
        "Assembly.dll not found. Build the Assembly project (Debug | x86) first.\n"
        f"Expected it at: {DLL_CANDIDATE_PATHS[0]}"
    )

# WinDLL = stdcall calling convention (matches ".model flat, stdcall").
# CDLL would leave the stack unbalanced and crash.
asm = ctypes.WinDLL(str(DLL_PATH))

# ---------------------------------------------------------------------------
# 3. Type names (ctypes type  <->  assembly type)
# ---------------------------------------------------------------------------
signed_int32 = ctypes.c_int32                            # SDWORD
unsigned_int32 = ctypes.c_uint32                         # DWORD
pointer_to_signed_int32 = ctypes.POINTER(signed_int32)   # PTR SDWORD
c_string_pointer = ctypes.c_char_p                       # PTR BYTE (null-terminated ASCII)

USERNAME_BUFFER_SIZE = 16                                # NAME_LEN in main.asm (15 chars + null)

# ---------------------------------------------------------------------------
# 4. Function signatures - they must mirror the PROC parameters in main.asm
# ---------------------------------------------------------------------------
asm.SignUp.argtypes       = [c_string_pointer, c_string_pointer]
asm.SignUp.restype        = signed_int32
asm.Login.argtypes        = [c_string_pointer, c_string_pointer]
asm.Login.restype         = signed_int32
asm.Logout.argtypes       = []
asm.Logout.restype        = None
asm.Deposit.argtypes      = [c_string_pointer]
asm.Deposit.restype       = signed_int32
asm.Withdraw.argtypes     = [c_string_pointer]
asm.Withdraw.restype      = signed_int32
asm.GetBalance.argtypes   = []
asm.GetBalance.restype    = signed_int32
asm.AttemptsLeft.argtypes = [c_string_pointer]
asm.AttemptsLeft.restype  = signed_int32
asm.GetRule.argtypes      = [signed_int32]
asm.GetRule.restype       = signed_int32
asm.GetUserCount.argtypes = []
asm.GetUserCount.restype  = signed_int32
asm.ImportUser.argtypes   = [c_string_pointer, unsigned_int32, signed_int32,
                             unsigned_int32, unsigned_int32]
asm.ImportUser.restype    = signed_int32
asm.ExportUser.argtypes   = [unsigned_int32, c_string_pointer, pointer_to_signed_int32]
asm.ExportUser.restype    = signed_int32


def _to_ascii_bytes(text):
    """Trim surrounding spaces and convert to ASCII bytes.

    Non-ASCII characters become '?', which the assembly code rejects
    (invalid name / invalid PIN / invalid amount), so no special case is needed.
    """
    return text.strip().encode("ascii", "replace")


# ---------------------------------------------------------------------------
# 5. Wrappers (names follow the assembly functions)
# ---------------------------------------------------------------------------
def sign_up(user_name, pin_text):
    """1 created | -1 name taken | -2 invalid name | -3 bank full | -4 invalid PIN"""
    return asm.SignUp(_to_ascii_bytes(user_name), _to_ascii_bytes(pin_text))


def login(user_name, pin_text):
    """1 success | 0 wrong PIN | -1 no such user | -2 account locked"""
    return asm.Login(_to_ascii_bytes(user_name), _to_ascii_bytes(pin_text))


def logout():
    """Forget the logged-in user (the session lives only in the asm memory)."""
    asm.Logout()


def deposit(amount_text):
    """Pass the RAW entry text; the assembly code decides whether it is valid."""
    return asm.Deposit(_to_ascii_bytes(amount_text))


def withdraw(amount_text):
    """Pass the RAW entry text; the assembly code decides whether it is valid."""
    return asm.Withdraw(_to_ascii_bytes(amount_text))


def get_balance():
    """Balance (whole rupees) of the logged-in user, 0 if nobody is logged in."""
    return asm.GetBalance()


def attempts_left(user_name):
    """Wrong-PIN tries left before the lock (0..3), -1 if no such user."""
    return asm.AttemptsLeft(_to_ascii_bytes(user_name))


def get_rule(rule_identifier):
    """0 note unit | 1 max withdraw | 2 max deposit | 3 max tries | 4 max balance."""
    return asm.GetRule(rule_identifier)


def get_user_count():
    """Number of accounts currently in the asm table."""
    return asm.GetUserCount()


def import_user(user_name, pin_hash, balance, failed_attempts, locked_flag):
    """file -> asm.  Returns 1 if asm accepted the record, 0 if it rejected it."""
    return asm.ImportUser(user_name.encode("ascii", "replace"),
                          pin_hash, balance, failed_attempts, locked_flag)


def export_user(row_index):
    """asm -> file.  Returns (name, pin_hash, balance, failed, locked) or None."""
    name_buffer = ctypes.create_string_buffer(USERNAME_BUFFER_SIZE)   # asm writes the name here
    field_values = (signed_int32 * 4)()      # asm writes {hash, balance, failed, locked} here
    if not asm.ExportUser(row_index, name_buffer, field_values):
        return None
    pin_hash_as_unsigned = field_values[0] & 0xFFFFFFFF   # the hash is unsigned, ctypes gave a signed int
    return (name_buffer.value.decode("ascii"), pin_hash_as_unsigned,
            field_values[1], field_values[2], field_values[3])


# ---------------------------------------------------------------------------
# 6. Console self-test:  uv run bridge.py      (replays the dry run of the documentation)
# ---------------------------------------------------------------------------
def run_self_test():
    expected_rules = (500, 25000, 200000, 3, 1000000000)
    assert tuple(get_rule(rule_id) for rule_id in range(5)) == expected_rules, "rule constants changed?"
    assert get_rule(99) == -1

    # sign-up validation
    assert sign_up("al", "1234") == -2          # name too short
    assert sign_up("ali!", "1234") == -2        # symbol in name
    assert sign_up("ali", "12a4") == -4         # PIN is not all digits
    assert sign_up("ali", "123") == -4          # PIN too short
    assert sign_up("ali", "1234") == 1          # created
    assert sign_up("ali", "9999") == -1         # duplicate name

    # login, attempts counter and session
    assert login("nobody", "1234") == -1
    assert login("ali", "0000") == 0 and attempts_left("ali") == 2
    assert login("ali", "1234") == 1            # success resets the counter
    assert attempts_left("ali") == 3

    # money rules
    assert deposit("10000") == 1
    assert deposit("12.5") == -2 and deposit("abc") == -2 and deposit("") == -2 and deposit("0") == -2
    assert deposit("200500") == -4
    assert withdraw("2300") == -3               # not a multiple of 500
    assert withdraw("25.5") == -2               # not a whole number
    assert withdraw("30000") == -4              # over the per-withdrawal limit
    assert withdraw("2500") == 1
    assert withdraw("25000") == 0               # passes unit + limit, but balance is only 7,500
    assert get_balance() == 7500

    # lockout (a second user)
    assert sign_up("bob", "4321") == 1
    assert [login("bob", "0000") for _ in range(3)] == [0, 0, -2]
    assert login("bob", "4321") == -2           # locked even with the right PIN

    # the two transfer doors used by storage.py
    assert get_user_count() == 2
    assert export_user(0)[0] == "ali" and export_user(0)[2] == 7500
    assert export_user(5) is None
    assert import_user("ali", 1, 0, 0, 0) == 0      # duplicate rejected
    assert import_user("x,y", 1, 0, 0, 0) == 0      # bad name rejected
    assert import_user("carl", 1, -5, 0, 0) == 0    # negative balance rejected
    assert import_user("carl", 1, 100, 0, 0) == 1   # valid record accepted

    # session end
    logout()
    assert withdraw("500") == -1                    # not logged in
    print("All asm self-tests passed")


if __name__ == "__main__":
    run_self_test()
    