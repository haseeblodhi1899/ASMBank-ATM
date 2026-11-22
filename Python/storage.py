"""storage.py - moves records between users.csv and the asm account table.

Python only TRANSPORTS data.  The assembly code owns the table and validates every
row it receives (ImportUser), so a hand-edited or corrupted file cannot break the rules.
"""
import csv
import os
import shutil
from pathlib import Path

import bridge

PYTHON_FOLDER = Path(__file__).resolve().parent
CSV_PATH = PYTHON_FOLDER / "users.csv"               # the persistent "database" file
TEMPORARY_PATH = PYTHON_FOLDER / "users.csv.tmp"     # written first, then swapped in (atomic save)
BACKUP_PATH = PYTHON_FOLDER / "users.csv.bak"        # copy of the original when rows were rejected
CSV_HEADER = ["username", "pin_hash", "balance", "failed", "locked"]


def fits_in_unsigned_32_bits(number):
    """Conversion safety: ctypes would silently truncate numbers that do not fit."""
    return 0 <= number <= 0xFFFFFFFF


def fits_in_signed_32_bits(number):
    """Same safety check for signed values (balances)."""
    return -2**31 <= number < 2**31


def load_users():
    """Read users.csv into the asm table.  Call ONCE at start-up.

    Returns (loaded_count, skipped_count).  Python only checks that the numbers fit
    their 32-bit slots; the MEANING (ranges, duplicates, name rules) is judged by asm.
    """
    if not CSV_PATH.exists():
        return 0, 0                                  # first run: start with an empty table

    loaded_count = 0
    skipped_count = 0
    # "utf-8-sig" also accepts a file saved by Excel with a byte-order mark.
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as csv_file:
        for row in csv.DictReader(csv_file):
            try:
                user_name = row["username"]
                pin_hash = int(row["pin_hash"])
                balance = int(row["balance"])
                failed_attempts = int(row["failed"])
                locked_flag = int(row["locked"])
                row_fits = (fits_in_unsigned_32_bits(pin_hash)
                            and fits_in_signed_32_bits(balance)
                            and fits_in_unsigned_32_bits(failed_attempts)
                            and fits_in_unsigned_32_bits(locked_flag)
                            and user_name.isascii())
            except (KeyError, ValueError, TypeError, AttributeError):
                row_fits = False                     # missing column, text instead of a number, ...

            if row_fits and bridge.import_user(user_name, pin_hash, balance,
                                               failed_attempts, locked_flag) == 1:
                loaded_count += 1
            else:
                skipped_count += 1

    if skipped_count:
        shutil.copyfile(CSV_PATH, BACKUP_PATH)       # keep the original before any rewrite
    return loaded_count, skipped_count


def save_users():
    """Write the asm table to users.csv atomically.  Returns True on success.

    The data goes to users.csv.tmp first and os.replace swaps it in, so a crash in the
    middle of saving can never leave a half-written users.csv behind.
    """
    try:
        with open(TEMPORARY_PATH, "w", newline="", encoding="utf-8") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(CSV_HEADER)
            for row_index in range(bridge.get_user_count()):
                csv_writer.writerow(bridge.export_user(row_index))   # name, hash, balance, failed, locked
        os.replace(TEMPORARY_PATH, CSV_PATH)         # atomic swap
        return True
    except OSError:                                  # e.g. users.csv is open in Excel
        try:
            TEMPORARY_PATH.unlink()                  # do not leave the half-finished temp file around
        except OSError:
            pass
        return False
