; =====================================================================
;  main.asm  ->  Assembly.dll      (MASM, x86, stdcall)
;
;  PURPOSE
;    ALL ATM rules, validation, arithmetic and the account table live in
;    this file.  Python (ctypes) only draws the GUI and moves records to and
;    from users.csv; it never edits a balance and never decides a rule.
;
;  BUILD
;    Visual Studio: Debug | x86 | Dynamic Library (.dll)
;    The exported names are listed in exports.def
;    Linker options: /NOENTRY  /SAFESEH:NO  (module definition file = exports.def)
;
;  CALLING CONVENTION (stdcall)
;    * Arguments are pushed right-to-left and the CALLEE removes them
;      (MASM writes the "ret n" for us), the result comes back in EAX.
;    * "USES" makes MASM save/restore the callee-saved registers
;      (EBX, ESI, EDI) so the caller's values survive the call.
;    * EAX, ECX and EDX are scratch registers: any call may overwrite them.
;
;  REGISTER ROLES USED IN THE COMMENTS BELOW
;    ESI / EDI = walking pointers into text   EBX = pointer to a USER record
;    EAX       = result / running value       ECX = counter     EDX = scratch
; =====================================================================
.386
.model flat, stdcall
option casemap:none              ; keep identifier case so names match exports.def

; ---------------------------------------------------------------------
;  ATM BUSINESS RULES  (Python reads these through GetRule)
; ---------------------------------------------------------------------
MAX_USERS            EQU 50              ; number of account slots in the table
NAME_LEN             EQU 16              ; username field: 15 characters + terminating 0
MAX_TRIES            EQU 3               ; wrong PINs in a row before the account locks
WITHDRAW_UNIT        EQU 500             ; cash comes in notes: withdraw multiples of 500
MAX_WITHDRAW         EQU 25000           ; largest single withdrawal
MAX_DEPOSIT          EQU 200000          ; largest single deposit
MAX_BALANCE          EQU 1000000000      ; account balance cap (keeps every sum inside int32)

; ---------------------------------------------------------------------
;  INPUT FORMAT LIMITS
; ---------------------------------------------------------------------
PIN_LENGTH           EQU 4               ; a PIN is exactly 4 digits
MIN_NAME_LENGTH      EQU 3               ; a username has at least 3 characters
MAX_AMOUNT_DIGITS    EQU 9               ; amount text may have at most 9 digits (< 10^9, no overflow)
HASH_START_VALUE     EQU 5381            ; djb2 starting value

; ---------------------------------------------------------------------
;  SPECIAL VALUES
; ---------------------------------------------------------------------
NO_USER_LOGGED_IN    EQU -1              ; value of currentUserIndex when nobody is logged in
USER_NOT_FOUND       EQU -1              ; FindUser result when the name is not in the table
INVALID_AMOUNT       EQU -1              ; ParseAmount result when the text is not a whole number
RESULT_YES           EQU 1               ; "true" result of the Is... helpers
RESULT_NO            EQU 0               ; "false" result of the Is... helpers

; ---------------------------------------------------------------------
;  RETURN CODES  (the contract with Python: bridge.py / messages.py)
; ---------------------------------------------------------------------
; SignUp
SIGNUP_CREATED               EQU 1
SIGNUP_NAME_TAKEN            EQU -1
SIGNUP_INVALID_NAME          EQU -2
SIGNUP_BANK_FULL             EQU -3
SIGNUP_INVALID_PIN           EQU -4

; Login
LOGIN_SUCCESS                EQU 1
LOGIN_WRONG_PIN              EQU 0
LOGIN_NO_SUCH_USER           EQU -1
LOGIN_ACCOUNT_LOCKED         EQU -2

; Deposit
DEPOSIT_SUCCESS              EQU 1
DEPOSIT_NOT_LOGGED_IN        EQU -1
DEPOSIT_INVALID_AMOUNT       EQU -2
DEPOSIT_OVER_LIMIT           EQU -4
DEPOSIT_OVER_ACCOUNT_CAP     EQU -5

; Withdraw
WITHDRAW_SUCCESS             EQU 1
WITHDRAW_INSUFFICIENT_FUNDS  EQU 0
WITHDRAW_NOT_LOGGED_IN       EQU -1
WITHDRAW_INVALID_AMOUNT      EQU -2
WITHDRAW_NOT_A_MULTIPLE      EQU -3
WITHDRAW_OVER_LIMIT          EQU -4

; AttemptsLeft / GetRule / ExportUser / ImportUser
ATTEMPTS_NO_SUCH_USER        EQU -1
RULE_UNKNOWN                 EQU -1
RECORD_ACCEPTED              EQU 1
RECORD_REJECTED              EQU 0

; GetRule identifiers
RULE_ID_WITHDRAW_UNIT        EQU 0
RULE_ID_MAX_WITHDRAW         EQU 1
RULE_ID_MAX_DEPOSIT          EQU 2
RULE_ID_MAX_TRIES            EQU 3
RULE_ID_MAX_BALANCE          EQU 4

; Layout of the int32[4] array that ExportUser fills for Python (byte offsets)
EXPORT_PIN_HASH_OFFSET       EQU 0
EXPORT_BALANCE_OFFSET        EQU 4
EXPORT_FAILED_OFFSET         EQU 8
EXPORT_LOCKED_OFFSET         EQU 12

; ---------------------------------------------------------------------
;  ONE ACCOUNT RECORD = 32 BYTES
; ---------------------------------------------------------------------
USER STRUCT
    userNameText        BYTE NAME_LEN DUP(0)   ; +0   username, null-terminated
    pinHashValue        DWORD 0                ; +16  hash of the PIN (the PIN itself is never stored)
    accountBalance      SDWORD 0               ; +20  whole rupees (signed 32-bit)
    failedAttemptCount  DWORD 0                ; +24  consecutive wrong PINs
    isLockedFlag        DWORD 0                ; +28  1 = account locked, 0 = active
USER ENDS

; ---------------------------------------------------------------------
;  GLOBAL DATA: the whole "database" lives here
; ---------------------------------------------------------------------
.data
userTable           USER MAX_USERS DUP(<>)     ; array of 50 account records
userCount           DWORD 0                    ; used slots (= index of the next free slot)
currentUserIndex    SDWORD NO_USER_LOGGED_IN   ; index of the logged-in user, -1 = nobody

.code

; =====================================================================
;  STRING HELPERS  (null-terminated ASCII strings)
; =====================================================================

; int StrLength(char* textPointer)  -> number of characters before the null
StrLength PROC USES esi, textPointer:PTR BYTE
    mov  esi, textPointer
    xor  eax, eax                          ; eax = length counter, starts at 0
StrLength_ScanLoop:
    cmp  BYTE PTR [esi+eax], 0             ; reached the terminating 0?
    je   StrLength_Done
    inc  eax                               ; one more character
    jmp  StrLength_ScanLoop
StrLength_Done:
    ret                                    ; eax = length
StrLength ENDP

; int StrEqual(char* firstTextPointer, char* secondTextPointer) -> 1 equal, 0 different
StrEqual PROC USES esi edi, firstTextPointer:PTR BYTE, secondTextPointer:PTR BYTE
    mov  esi, firstTextPointer
    mov  edi, secondTextPointer
StrEqual_CompareLoop:
    mov  al, [esi]                         ; character from the first string
    cmp  al, [edi]                         ; same character in the second string?
    jne  StrEqual_Different
    cmp  al, 0
    je   StrEqual_Same                     ; both strings reached their null together
    inc  esi
    inc  edi
    jmp  StrEqual_CompareLoop
StrEqual_Same:
    mov  eax, RESULT_YES
    ret
StrEqual_Different:
    mov  eax, RESULT_NO
    ret
StrEqual ENDP

; void StrCopy(char* destinationPointer, char* sourcePointer)   copies including the null
StrCopy PROC USES esi edi, destinationPointer:PTR BYTE, sourcePointer:PTR BYTE
    mov  esi, sourcePointer
    mov  edi, destinationPointer
StrCopy_CopyLoop:
    mov  al, [esi]                         ; read one character
    mov  [edi], al                         ; write it
    inc  esi
    inc  edi
    cmp  al, 0                             ; stop AFTER the null has been copied
    jne  StrCopy_CopyLoop
    ret
StrCopy ENDP

; =====================================================================
;  VALIDATION / PARSING HELPERS
; =====================================================================

; uint HashPin(char* textPointer)
;   djb2 hash:  hash = 5381;  for each character: hash = hash * 33 + character
;   hash * 33 is computed as (hash << 5) + hash; the 32-bit wrap-around is the modulo 2^32.
HashPin PROC USES esi ebx, textPointer:PTR BYTE
    mov  esi, textPointer
    mov  eax, HASH_START_VALUE             ; eax = running hash
HashPin_NextCharacter:
    movzx ebx, BYTE PTR [esi]              ; ebx = current character (zero-extended)
    cmp  ebx, 0
    je   HashPin_Done                      ; end of text
    mov  edx, eax                          ; edx = old hash
    shl  eax, 5                            ; eax = hash * 32
    add  eax, edx                          ; eax = hash * 33
    add  eax, ebx                          ; + character code
    inc  esi
    jmp  HashPin_NextCharacter
HashPin_Done:
    ret                                    ; eax = hash
HashPin ENDP

; int IsValidPin(char* pinTextPointer)  -> 1 if the text is exactly 4 digits
IsValidPin PROC USES esi, pinTextPointer:PTR BYTE
    mov  esi, pinTextPointer
    xor  ecx, ecx                          ; ecx = digits seen so far
IsValidPin_ReadLoop:
    mov  al, [esi+ecx]
    cmp  al, 0
    je   IsValidPin_EndOfText
    cmp  al, '0'
    jb   IsValidPin_Invalid                ; below '0' (unsigned compare)
    cmp  al, '9'
    ja   IsValidPin_Invalid                ; above '9'
    inc  ecx
    jmp  IsValidPin_ReadLoop
IsValidPin_EndOfText:
    cmp  ecx, PIN_LENGTH                   ; exactly 4 digits?
    jne  IsValidPin_Invalid
    mov  eax, RESULT_YES
    ret
IsValidPin_Invalid:
    mov  eax, RESULT_NO
    ret
IsValidPin ENDP

; int IsValidName(char* userNamePointer)  -> 1 if 3..15 characters, only A-Z a-z 0-9
IsValidName PROC USES esi, userNamePointer:PTR BYTE
    mov  esi, userNamePointer
    xor  ecx, ecx                          ; ecx = characters seen so far
IsValidName_ReadLoop:
    mov  al, [esi+ecx]
    cmp  al, 0
    je   IsValidName_EndOfText             ; reached the null terminator
    cmp  al, '0'
    jb   IsValidName_Invalid               ; below '0'  (space , . - ! ...)
    cmp  al, '9'
    jbe  IsValidName_CharacterOk           ; '0'..'9'
    cmp  al, 'A'
    jb   IsValidName_Invalid               ; between '9' and 'A'
    cmp  al, 'Z'
    jbe  IsValidName_CharacterOk           ; 'A'..'Z'
    cmp  al, 'a'
    jb   IsValidName_Invalid               ; between 'Z' and 'a'
    cmp  al, 'z'
    ja   IsValidName_Invalid               ; above 'z'
IsValidName_CharacterOk:
    inc  ecx
    jmp  IsValidName_ReadLoop
IsValidName_EndOfText:
    cmp  ecx, MIN_NAME_LENGTH
    jb   IsValidName_Invalid               ; too short
    cmp  ecx, NAME_LEN - 1
    ja   IsValidName_Invalid               ; too long for the 16-byte field
    mov  eax, RESULT_YES
    ret
IsValidName_Invalid:
    mov  eax, RESULT_NO
    ret
IsValidName ENDP

; int ParseAmount(char* amountTextPointer)  -> number >= 0, or -1 if not a whole number
;   "2500" -> 2500    "25.5" -> -1    "abc" -> -1    "" -> -1    10+ digits -> -1
;   Value is built as  value = value * 10 + (character - '0').
ParseAmount PROC USES esi ebx, amountTextPointer:PTR BYTE
    mov  esi, amountTextPointer
    xor  eax, eax                          ; eax = running value
    xor  ecx, ecx                          ; ecx = number of digits read
ParseAmount_ReadLoop:
    movzx ebx, BYTE PTR [esi]              ; ebx = current character
    cmp  ebx, 0
    je   ParseAmount_EndOfText
    cmp  ebx, '0'
    jb   ParseAmount_NotANumber            ; not a digit ('.' and '-' land here)
    cmp  ebx, '9'
    ja   ParseAmount_NotANumber
    inc  ecx
    cmp  ecx, MAX_AMOUNT_DIGITS
    ja   ParseAmount_NotANumber            ; more than 9 digits: refuse (value stays < 10^9)
    imul eax, eax, 10                      ; value = value * 10
    sub  ebx, '0'                          ; ASCII code -> digit value 0..9
    add  eax, ebx                          ; value = value + digit
    inc  esi
    jmp  ParseAmount_ReadLoop
ParseAmount_EndOfText:
    cmp  ecx, 0
    je   ParseAmount_NotANumber            ; empty text is not a number
    ret                                    ; eax = parsed number
ParseAmount_NotANumber:
    mov  eax, INVALID_AMOUNT
    ret
ParseAmount ENDP

; =====================================================================
;  TABLE HELPERS
; =====================================================================

; int FindUser(char* userNamePointer)  -> index of the user, or -1 (USER_NOT_FOUND)
;   Linear search over userTable[0 .. userCount-1].
FindUser PROC USES ebx esi, userNamePointer:PTR BYTE
    xor  ebx, ebx                          ; ebx = candidate index i, starts at 0
FindUser_SearchLoop:
    cmp  ebx, userCount
    jae  FindUser_NotFound                 ; i >= userCount (unsigned): searched everything
    mov  esi, ebx
    imul esi, SIZEOF USER                  ; byte offset = i * 32
    add  esi, OFFSET userTable             ; esi -> userTable[i]  (the name is the first field)
    INVOKE StrEqual, userNamePointer, esi
    cmp  eax, RESULT_YES
    je   FindUser_Found
    inc  ebx
    jmp  FindUser_SearchLoop
FindUser_Found:
    mov  eax, ebx                          ; return the index
    ret
FindUser_NotFound:
    mov  eax, USER_NOT_FOUND
    ret
FindUser ENDP

; USER* CurRecord(void)  -> pointer to the logged-in record, 0 if nobody is logged in
CurRecord PROC
    mov  eax, currentUserIndex
    cmp  eax, 0
    jl   CurRecord_Nobody                  ; negative (-1) -> nobody logged in (signed compare)
    imul eax, SIZEOF USER                  ; byte offset = index * 32
    add  eax, OFFSET userTable             ; address = base + offset
    ret
CurRecord_Nobody:
    xor  eax, eax                          ; null pointer
    ret
CurRecord ENDP

; =====================================================================
;  EXPORTED API  (these names are listed in exports.def)
; =====================================================================

; int SignUp(char* userNamePointer, char* pinTextPointer)
;   1 created | -1 name taken | -2 invalid name | -3 bank full | -4 invalid PIN
SignUp PROC USES ebx, userNamePointer:PTR BYTE, pinTextPointer:PTR BYTE
    INVOKE IsValidName, userNamePointer
    cmp  eax, RESULT_YES
    jne  SignUp_InvalidName
    INVOKE IsValidPin, pinTextPointer
    cmp  eax, RESULT_YES
    jne  SignUp_InvalidPin
    INVOKE FindUser, userNamePointer
    cmp  eax, USER_NOT_FOUND
    jne  SignUp_NameTaken                  ; an index came back -> the name already exists
    cmp  userCount, MAX_USERS
    jae  SignUp_BankFull                   ; no free slot (unsigned compare)
    mov  ebx, userCount
    imul ebx, SIZEOF USER
    add  ebx, OFFSET userTable             ; ebx -> first free slot
    INVOKE StrCopy, ebx, userNamePointer   ; the name is the first field of the record
    INVOKE HashPin, pinTextPointer
    mov  (USER PTR [ebx]).pinHashValue, eax        ; store the hash, never the PIN
    mov  (USER PTR [ebx]).accountBalance, 0        ; new accounts start empty
    mov  (USER PTR [ebx]).failedAttemptCount, 0
    mov  (USER PTR [ebx]).isLockedFlag, 0
    inc  userCount                                 ; the slot is now in use
    mov  eax, SIGNUP_CREATED
    ret
SignUp_NameTaken:
    mov  eax, SIGNUP_NAME_TAKEN
    ret
SignUp_InvalidName:
    mov  eax, SIGNUP_INVALID_NAME
    ret
SignUp_BankFull:
    mov  eax, SIGNUP_BANK_FULL
    ret
SignUp_InvalidPin:
    mov  eax, SIGNUP_INVALID_PIN
    ret
SignUp ENDP

; int Login(char* userNamePointer, char* pinTextPointer)
;   1 success | 0 wrong PIN | -1 no such user | -2 account locked
Login PROC USES ebx esi, userNamePointer:PTR BYTE, pinTextPointer:PTR BYTE
    INVOKE FindUser, userNamePointer
    cmp  eax, USER_NOT_FOUND
    je   Login_NoSuchUser
    mov  esi, eax                          ; esi = index of the user
    mov  ebx, eax
    imul ebx, SIZEOF USER
    add  ebx, OFFSET userTable             ; ebx -> the user's record
    cmp  (USER PTR [ebx]).isLockedFlag, 1
    je   Login_AccountLocked               ; locked accounts never log in, even with the right PIN
    INVOKE HashPin, pinTextPointer         ; hash what was typed
    cmp  eax, (USER PTR [ebx]).pinHashValue
    jne  Login_WrongPin
    mov  (USER PTR [ebx]).failedAttemptCount, 0    ; success: reset the failure counter
    mov  currentUserIndex, esi                     ; remember who is logged in
    mov  eax, LOGIN_SUCCESS
    ret
Login_WrongPin:
    inc  (USER PTR [ebx]).failedAttemptCount       ; one more failure
    cmp  (USER PTR [ebx]).failedAttemptCount, MAX_TRIES
    jb   Login_WrongPinStillHasTries               ; fewer than 3 failures so far (unsigned)
    mov  (USER PTR [ebx]).isLockedFlag, 1          ; the 3rd failure locks the account
Login_AccountLocked:
    mov  eax, LOGIN_ACCOUNT_LOCKED
    ret
Login_WrongPinStillHasTries:
    mov  eax, LOGIN_WRONG_PIN
    ret
Login_NoSuchUser:
    mov  eax, LOGIN_NO_SUCH_USER
    ret
Login ENDP

; void Logout(void)
Logout PROC
    mov  currentUserIndex, NO_USER_LOGGED_IN       ; forget the session
    ret
Logout ENDP

; int Deposit(char* amountTextPointer)
;   1 ok | -1 not logged in | -2 invalid amount | -4 over limit | -5 account cap
;   Check order (first failure wins): logged in -> parse -> per-deposit limit -> account cap
Deposit PROC USES ebx, amountTextPointer:PTR BYTE
    INVOKE CurRecord                       ; check 1: is somebody logged in?
    test eax, eax
    jz   Deposit_NotLoggedIn
    mov  ebx, eax                          ; ebx -> the logged-in user's record
    INVOKE ParseAmount, amountTextPointer  ; check 2: is it a whole number?
    cmp  eax, 1
    jl   Deposit_InvalidAmount             ; -1 (not a number) or 0 (zero): signed compare
    cmp  eax, MAX_DEPOSIT
    jg   Deposit_OverLimit                 ; check 3: per-deposit limit
    mov  edx, (USER PTR [ebx]).accountBalance
    add  edx, eax                          ; edx = balance AFTER the deposit
    cmp  edx, MAX_BALANCE
    jg   Deposit_OverAccountCap            ; check 4: account balance cap
    mov  (USER PTR [ebx]).accountBalance, edx      ; commit the new balance
    mov  eax, DEPOSIT_SUCCESS
    ret
Deposit_NotLoggedIn:
    mov  eax, DEPOSIT_NOT_LOGGED_IN
    ret
Deposit_InvalidAmount:
    mov  eax, DEPOSIT_INVALID_AMOUNT
    ret
Deposit_OverLimit:
    mov  eax, DEPOSIT_OVER_LIMIT
    ret
Deposit_OverAccountCap:
    mov  eax, DEPOSIT_OVER_ACCOUNT_CAP
    ret
Deposit ENDP

; int Withdraw(char* amountTextPointer)
;   1 ok | 0 insufficient funds | -1 not logged in | -2 invalid amount
;   -3 not a multiple of WITHDRAW_UNIT | -4 over the per-withdrawal limit
;   Check order (first failure wins): logged in -> parse -> multiple of 500 -> limit -> funds
Withdraw PROC USES ebx esi, amountTextPointer:PTR BYTE
    INVOKE CurRecord                       ; check 1: is somebody logged in?
    test eax, eax
    jz   Withdraw_NotLoggedIn
    mov  ebx, eax                          ; ebx -> the logged-in user's record
    INVOKE ParseAmount, amountTextPointer  ; check 2: is it a whole number?
    cmp  eax, 1
    jl   Withdraw_InvalidAmount            ; -1 (not a number) or 0 (zero)
    mov  esi, eax                          ; esi = requested amount (kept safe from div)
    xor  edx, edx                          ; div works on EDX:EAX, so clear EDX first
    mov  ecx, WITHDRAW_UNIT
    div  ecx                               ; eax = amount / 500, edx = amount mod 500
    cmp  edx, 0
    jne  Withdraw_NotAMultiple             ; check 3: must be a whole number of notes
    cmp  esi, MAX_WITHDRAW
    jg   Withdraw_OverLimit                ; check 4: per-withdrawal limit
    mov  eax, (USER PTR [ebx]).accountBalance
    cmp  eax, esi
    jl   Withdraw_InsufficientFunds        ; check 5: enough money? (signed compare)
    sub  eax, esi                          ; balance = balance - amount
    mov  (USER PTR [ebx]).accountBalance, eax      ; commit the new balance
    mov  eax, WITHDRAW_SUCCESS
    ret
Withdraw_InsufficientFunds:
    mov  eax, WITHDRAW_INSUFFICIENT_FUNDS
    ret
Withdraw_NotLoggedIn:
    mov  eax, WITHDRAW_NOT_LOGGED_IN
    ret
Withdraw_InvalidAmount:
    mov  eax, WITHDRAW_INVALID_AMOUNT
    ret
Withdraw_NotAMultiple:
    mov  eax, WITHDRAW_NOT_A_MULTIPLE
    ret
Withdraw_OverLimit:
    mov  eax, WITHDRAW_OVER_LIMIT
    ret
Withdraw ENDP

; int GetBalance(void)  -> balance of the logged-in user (0 if nobody is logged in)
GetBalance PROC
    INVOKE CurRecord
    test eax, eax
    jz   GetBalance_Nobody
    mov  eax, (USER PTR [eax]).accountBalance
    ret
GetBalance_Nobody:
    xor  eax, eax
    ret
GetBalance ENDP

; int AttemptsLeft(char* userNamePointer)  -> tries left before the lock (0..3), -1 if no such user
AttemptsLeft PROC USES ebx, userNamePointer:PTR BYTE
    INVOKE FindUser, userNamePointer
    cmp  eax, USER_NOT_FOUND
    je   AttemptsLeft_NoSuchUser
    imul eax, SIZEOF USER
    add  eax, OFFSET userTable
    mov  ebx, eax                          ; ebx -> the user's record
    mov  eax, MAX_TRIES
    sub  eax, (USER PTR [ebx]).failedAttemptCount  ; tries left = 3 - failures
    ret
AttemptsLeft_NoSuchUser:
    mov  eax, ATTEMPTS_NO_SUCH_USER
    ret
AttemptsLeft ENDP

; int GetRule(int ruleIdentifier)
;   0 note unit | 1 max withdraw | 2 max deposit | 3 max tries | 4 max balance | -1 unknown id
GetRule PROC ruleIdentifier:DWORD
    mov  eax, ruleIdentifier
    cmp  eax, RULE_ID_WITHDRAW_UNIT
    je   GetRule_WithdrawUnit
    cmp  eax, RULE_ID_MAX_WITHDRAW
    je   GetRule_MaxWithdraw
    cmp  eax, RULE_ID_MAX_DEPOSIT
    je   GetRule_MaxDeposit
    cmp  eax, RULE_ID_MAX_TRIES
    je   GetRule_MaxTries
    cmp  eax, RULE_ID_MAX_BALANCE
    je   GetRule_MaxBalance
    mov  eax, RULE_UNKNOWN                 ; unknown identifier
    ret
GetRule_WithdrawUnit:
    mov  eax, WITHDRAW_UNIT
    ret
GetRule_MaxWithdraw:
    mov  eax, MAX_WITHDRAW
    ret
GetRule_MaxDeposit:
    mov  eax, MAX_DEPOSIT
    ret
GetRule_MaxTries:
    mov  eax, MAX_TRIES
    ret
GetRule_MaxBalance:
    mov  eax, MAX_BALANCE
    ret
GetRule ENDP

; int GetUserCount(void)  -> number of accounts in the table
GetUserCount PROC
    mov  eax, userCount
    ret
GetUserCount ENDP

; =====================================================================
;  DATA TRANSFER DOORS  (Python <-> asm table, used for users.csv)
; =====================================================================

; int ExportUser(uint rowIndex, char* outputNamePointer, int32* outputFieldsPointer)
;   outputNamePointer needs 16 bytes;
;   outputFieldsPointer = int32[4] receiving {pinHash, balance, failedCount, lockedFlag}
;   returns 1 ok, 0 if rowIndex is out of range
ExportUser PROC USES ebx, rowIndex:DWORD, outputNamePointer:PTR BYTE, outputFieldsPointer:PTR SDWORD
    mov  ebx, rowIndex
    cmp  ebx, userCount
    jae  ExportUser_OutOfRange             ; rowIndex >= userCount (unsigned)
    imul ebx, SIZEOF USER
    add  ebx, OFFSET userTable             ; ebx -> the requested record
    INVOKE StrCopy, outputNamePointer, ebx ; copy the name into Python's buffer
    mov  edx, outputFieldsPointer          ; load AFTER the INVOKE (EDX is a scratch register)
    mov  eax, (USER PTR [ebx]).pinHashValue
    mov  [edx + EXPORT_PIN_HASH_OFFSET], eax
    mov  eax, (USER PTR [ebx]).accountBalance
    mov  [edx + EXPORT_BALANCE_OFFSET], eax
    mov  eax, (USER PTR [ebx]).failedAttemptCount
    mov  [edx + EXPORT_FAILED_OFFSET], eax
    mov  eax, (USER PTR [ebx]).isLockedFlag
    mov  [edx + EXPORT_LOCKED_OFFSET], eax
    mov  eax, RECORD_ACCEPTED
    ret
ExportUser_OutOfRange:
    mov  eax, RECORD_REJECTED
    ret
ExportUser ENDP

; int ImportUser(char* importedNamePointer, uint importedPinHash, int importedBalance,
;                uint importedFailedCount, uint importedLockedFlag)
;   Appends one record read from users.csv.  1 accepted, 0 rejected.
;   Everything that comes from a file is UNTRUSTED, so every field is re-validated here.
ImportUser PROC USES ebx, importedNamePointer:PTR BYTE, importedPinHash:DWORD, importedBalance:SDWORD, importedFailedCount:DWORD, importedLockedFlag:DWORD
    cmp  userCount, MAX_USERS
    jae  ImportUser_Rejected               ; table is full
    INVOKE IsValidName, importedNamePointer
    cmp  eax, RESULT_YES
    jne  ImportUser_Rejected               ; bad name (this also guards the 16-byte name field)
    INVOKE FindUser, importedNamePointer
    cmp  eax, USER_NOT_FOUND
    jne  ImportUser_Rejected               ; duplicate username in the file
    cmp  importedBalance, 0
    jl   ImportUser_Rejected               ; negative balance (signed compare)
    cmp  importedBalance, MAX_BALANCE
    jg   ImportUser_Rejected               ; above the account cap
    cmp  importedFailedCount, MAX_TRIES
    ja   ImportUser_Rejected               ; impossible failure counter (unsigned compare)
    cmp  importedLockedFlag, 1
    ja   ImportUser_Rejected               ; the lock flag must be 0 or 1
    mov  ebx, userCount
    imul ebx, SIZEOF USER
    add  ebx, OFFSET userTable             ; ebx -> first free slot
    INVOKE StrCopy, ebx, importedNamePointer
    mov  eax, importedPinHash
    mov  (USER PTR [ebx]).pinHashValue, eax
    mov  eax, importedBalance
    mov  (USER PTR [ebx]).accountBalance, eax
    mov  eax, importedFailedCount
    mov  (USER PTR [ebx]).failedAttemptCount, eax
    mov  eax, importedLockedFlag
    mov  (USER PTR [ebx]).isLockedFlag, eax
    inc  userCount                         ; the slot is now in use
    mov  eax, RECORD_ACCEPTED
    ret
ImportUser_Rejected:
    mov  eax, RECORD_REJECTED
    ret
ImportUser ENDP

END                                        ; no entry label: this is a DLL
