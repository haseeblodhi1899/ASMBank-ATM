# ASMBank ATM

<div align="center">

![Assembly](https://img.shields.io/badge/assembly-MASM%20x86-informational)
![Python](https://img.shields.io/badge/python-3.12%20(32--bit)-yellow)
![GUI](https://img.shields.io/badge/GUI-CustomTkinter-success)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Package manager](https://img.shields.io/badge/package%20manager-uv-blueviolet)
![Commits](https://img.shields.io/badge/commits-conventional-fe5196)

</div>

An ATM simulator for my COAL (Computer Organization and Assembly Language) project. All the banking logic (validation, PIN hashing, limits, balances, lockout) is written in x86 assembly (MASM) and built as a DLL. Python only draws the GUI (CustomTkinter) and saves/loads the accounts in a CSV file.

## Requirements

- Windows 10 or 11 (64-bit)
- [uv](https://docs.astral.sh/uv/) (it installs Python for you)
- Git
- Visual Studio with the "Desktop development with C++" workload (only needed if you want to rebuild the DLL)

You do not need a system-wide Python or the Irvine32 library.

The DLL is 32-bit (x86), so Python has to be 32-bit too. A process can only load DLLs of the same bitness. uv installs a separate 32-bit Python for this project, so your normal 64-bit Python is not touched.

## Setup

1. Install uv (PowerShell), then close and reopen the terminal:
   
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. Clone the repository:
   
   ```powershell
   git clone https://github.com/haseeblodhi1899/ASMBank-ATM.git
   cd ASMBank-ATM\Python
   ```

3. Install Python and all packages with one command:

   ```powershell
   uv sync
   ```

   This reads `.python-version` and `uv.lock`, downloads 32-bit Python 3.12 if you do not have it, creates a `.venv` folder and installs the packages.

4. Check that Python is 32-bit (it must print `32`):

   ```powershell
   uv run python -c "import struct; print(struct.calcsize('P')*8)"
   ```

What `uv sync` installs:

| Item | Version | Why |
|---|---|---|
| Python (32-bit) | 3.12 | must match the 32-bit DLL |
| customtkinter | 6.0.0 | the GUI |
| darkdetect | 0.8.0 | needed by customtkinter |
| packaging | 26.3 | needed by customtkinter |

Everything else the code uses (`tkinter`, `ctypes`, `csv`) comes with Python. uv, Git and Visual Studio are not installed by `uv sync`.

## Run

The repo already contains the built `Assembly/Debug/Assembly.dll`, so you can run the app directly:

```powershell
uv run app.py
```

`users.csv` is created in the `Python` folder after the first sign-up.

## Test

This runs a console self-test of the assembly code (sign-up checks, login, lockout, deposit/withdraw rules, import/export):

```powershell
uv run bridge.py
```

The last line should be `All asm self-tests passed`.

## Rebuild the DLL (optional)

Only needed if you change `main.asm` or `exports.def`.

1. Close the app (Windows locks the DLL while Python has it loaded).
2. Open `Assembly\Assembly.slnx` in Visual Studio.
3. Select **Debug** and **x86**.
4. Click **Build > Rebuild Solution**.

If you create the Visual Studio project yourself, use an Empty Project named `Assembly`, enable the **masm** build customization, set `main.asm` to *Microsoft Macro Assembler*, and use these properties (All Configurations, Win32):

| Page              | Property                          | Value                  |
| ----------------- | --------------------------------- | ---------------------- |
| General           | Configuration Type                | Dynamic Library (.dll) |
| Linker > Input    | Module Definition File            | `exports.def`          |
| Linker > Input    | Add Module to Assembly            | empty                  |
| Linker > Advanced | No Entry Point                    | Yes (`/NOENTRY`)       |
| Linker > Advanced | Entry Point                       | empty                  |
| Linker > Advanced | Image Has Safe Exception Handlers | No (`/SAFESEH:NO`)     |

Do not put `exports.def` in *Add Module to Assembly*. The build still succeeds but the DLL exports nothing.

To check the build, open a Developer Command Prompt for VS and run:

```
cd /d "<path>\ASMBank-ATM\Assembly"
dumpbin /headers Debug\Assembly.dll | findstr machine
dumpbin /exports Debug\Assembly.dll
```

You should see `14C machine (x86)` and 11 exported functions.

## Features

- Sign up, log in, deposit, withdraw and check balance
- PIN is stored as a hash, never as plain text
- Account locks after 3 wrong PINs
- Withdrawals in multiples of Rs 500, with limits for each transaction
- Accounts are saved in `users.csv` and loaded again on start
- Transaction receipt, on-screen keypad and a loading screen
- Automatic logout after 60 seconds of inactivity
- Window layout and fonts resize with the window

## How it works

```
app.py (GUI)  ->  bridge.py (ctypes)  ->  Assembly.dll (all rules and data)
                  storage.py <-> users.csv
                  messages.py (status code -> text)
```

| File                   | What it does                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| `Assembly/main.asm`    | Validation, PIN hashing, amount parsing, deposit/withdraw, lockout, session, account table |
| `Assembly/exports.def` | Lists the functions exported from the DLL                                                  |
| `Python/bridge.py`     | ctypes wrapper that calls the DLL. It has no rules                                         |
| `Python/storage.py`    | Reads and writes `users.csv` using `ImportUser` and `ExportUser`                           |
| `Python/messages.py`   | Turns status codes into the text shown in the GUI                                          |
| `Python/app.py`        | The GUI                                                                                    |

Python never changes a balance or decides a rule. The assembly code does that, and it also checks every row it reads from `users.csv`.

## Project structure

```
ASMBank-ATM/
├── README.md
├── .gitignore
├── Assembly/
│   ├── Assembly.slnx
│   ├── Assembly.vcxproj
│   ├── Assembly.vcxproj.filters
│   ├── exports.def
│   ├── main.asm
│   └── Debug/
│       └── Assembly.dll
└── Python/
    ├── .python-version
    ├── pyproject.toml
    ├── uv.lock
    ├── app.py
    ├── bridge.py
    ├── messages.py
    └── storage.py
```

## Rules

These are constants at the top of `main.asm`. If you change one and rebuild, the GUI messages update by themselves.

| Rule                   | Value                                   |
| ---------------------- | --------------------------------------- |
| Withdraw unit          | Rs 500                                  |
| Max per withdrawal     | Rs 25,000                               |
| Max per deposit        | Rs 200,000                              |
| Max balance            | Rs 1,000,000,000                        |
| Wrong PINs before lock | 3                                       |
| Max accounts           | 50                                      |
| Username               | 3-15 letters or digits (case-sensitive) |
| PIN                    | exactly 4 digits                        |
| Amount                 | whole numbers only                      |

## DLL functions

All functions use the stdcall convention.

| Function                                          | Return values                                                                                            |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `SignUp(name, pin)`                               | 1 created, -1 name taken, -2 invalid name, -3 bank full, -4 invalid PIN                                  |
| `Login(name, pin)`                                | 1 success, 0 wrong PIN, -1 no such user, -2 locked                                                       |
| `Logout()`                                        | nothing                                                                                                  |
| `Deposit(amount)`                                 | 1 ok, -1 not logged in, -2 invalid amount, -4 over limit, -5 over account cap                            |
| `Withdraw(amount)`                                | 1 ok, 0 not enough balance, -1 not logged in, -2 invalid amount, -3 not a multiple of 500, -4 over limit |
| `GetBalance()`                                    | balance in rupees                                                                                        |
| `AttemptsLeft(name)`                              | 0 to 3, or -1 if no such user                                                                            |
| `GetRule(id)`                                     | 0 note unit, 1 max withdraw, 2 max deposit, 3 max tries, 4 max balance, -1 unknown id                    |
| `GetUserCount()`                                  | number of accounts                                                                                       |
| `ImportUser(name, hash, balance, failed, locked)` | 1 accepted, 0 rejected                                                                                   |
| `ExportUser(index, nameOut, fieldsOut)`           | 1 ok, 0 index out of range                                                                               |

## users.csv

```
username,pin_hash,balance,failed,locked
ali,2088290703,7500,0,0
```

- `pin_hash` is the djb2 hash of the PIN
- `balance` is in whole rupees
- `failed` is the number of wrong PINs in a row
- `locked` is 1 if the account is locked

Rows that fail the assembly checks are skipped and the original file is copied to `users.csv.bak`. Saving writes to `users.csv.tmp` first and then swaps it in, so a crash cannot leave a half-written file. Do not keep `users.csv` open in Excel while the app runs, because saving will fail.

## Common problems

| Problem                                   | Fix                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------- |
| `uv` is not recognized                    | Close and reopen the terminal (and VS Code)                                                 |
| `WinError 193` or "Need 32-bit Python"    | Run with `uv run` inside the `Python` folder                                                |
| `Assembly.dll not found`                  | Build the project as Debug / x86                                                            |
| `AttributeError: function 'X' not found`  | `X` is missing from `exports.def` (names are case-sensitive). Fix it and rebuild            |
| `dumpbin /exports` shows nothing          | `exports.def` is in the wrong linker field. Move it to *Module Definition File* and rebuild |
| `LNK2001 ... _DllMainCRTStartup@12`       | Set `/NOENTRY` and clear *Entry Point*                                                      |
| `LNK2026 ... SAFESEH`                     | Set `/SAFESEH:NO`                                                                           |
| `LNK1104 cannot open irvine32.lib`        | Remove Irvine32 from the linker settings                                                    |
| `cannot open Assembly.dll` while building | Close the app and build again                                                               |
| Output goes to `x64\Debug`                | Switch the platform to x86 and rebuild                                                      |
| `ModuleNotFoundError: customtkinter`      | Use `uv run app.py` (run `uv sync` once)                                                    |
| "users.csv could not be saved"            | Close it if it is open in Excel                                                             |
| uv cannot find 32-bit Python              | Run `uv python install cpython-3.12-windows-x86-none`, or find the right name with `uv python list` |

## Limitations

- Windows only, and it needs 32-bit Python
- A locked account cannot be unlocked from the app (edit its row in `users.csv`)
- No transaction history, only a receipt after each transaction
- Maximum 50 accounts
- The PIN hash (djb2) is simple and not secure enough for a real bank
- No cents, only whole rupees
