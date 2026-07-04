"""UDS (ISO 14229) service identifiers and negative-response codes.

Constants + name lookups only — no behaviour. Hand-transcribed from ISO 14229-1.
A UDS request is ``[SID, ...params]``; a positive response is
``[SID + 0x40, ...data]``; a negative response is ``[0x7F, SID, NRC]``.
"""
from __future__ import annotations

POSITIVE_RESPONSE_OFFSET = 0x40
NEGATIVE_RESPONSE_SID = 0x7F
SUPPRESS_POSITIVE_RESPONSE_BIT = 0x80

# --- Service Identifiers (SIDs) -----------------------------------------
DIAGNOSTIC_SESSION_CONTROL = 0x10
ECU_RESET = 0x11
CLEAR_DIAGNOSTIC_INFORMATION = 0x14
READ_DTC_INFORMATION = 0x19
READ_DATA_BY_IDENTIFIER = 0x22
READ_MEMORY_BY_ADDRESS = 0x23
SECURITY_ACCESS = 0x27
COMMUNICATION_CONTROL = 0x28
WRITE_DATA_BY_IDENTIFIER = 0x2E
INPUT_OUTPUT_CONTROL_BY_IDENTIFIER = 0x2F
ROUTINE_CONTROL = 0x31
REQUEST_DOWNLOAD = 0x34
TRANSFER_DATA = 0x36
REQUEST_TRANSFER_EXIT = 0x37
TESTER_PRESENT = 0x3E
CONTROL_DTC_SETTING = 0x85

# --- Diagnostic sessions (0x10 sub-functions) ---------------------------
SESSION_DEFAULT = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED = 0x03

# --- ECU reset types (0x11 sub-functions) -------------------------------
RESET_HARD = 0x01
RESET_KEY_OFF_ON = 0x02
RESET_SOFT = 0x03

# --- InputOutputControl options (0x2F control byte) ---------------------
IO_RETURN_CONTROL_TO_ECU = 0x00
IO_RESET_TO_DEFAULT = 0x01
IO_FREEZE_CURRENT_STATE = 0x02
IO_SHORT_TERM_ADJUSTMENT = 0x03

# --- RoutineControl sub-functions (0x31) --------------------------------
ROUTINE_START = 0x01
ROUTINE_STOP = 0x02
ROUTINE_REQUEST_RESULTS = 0x03

# --- ReadDTCInformation sub-functions (0x19) ----------------------------
REPORT_DTC_BY_STATUS_MASK = 0x02

# --- Negative Response Codes (NRCs) -------------------------------------
NRC_GENERAL_REJECT = 0x10
NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_INCORRECT_LENGTH_OR_FORMAT = 0x13
NRC_RESPONSE_TOO_LONG = 0x14
NRC_BUSY_REPEAT_REQUEST = 0x21
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_EXCEED_NUMBER_OF_ATTEMPTS = 0x36
NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
NRC_GENERAL_PROGRAMMING_FAILURE = 0x72
NRC_RESPONSE_PENDING = 0x78  # not a final failure — keep waiting
NRC_SUBFUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7E
NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7F

_NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x72: "generalProgrammingFailure",
    0x78: "requestCorrectlyReceived-ResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


def nrc_name(code: int) -> str:
    """Human-readable name for a negative-response code."""
    return _NRC_NAMES.get(code, f"unknown(0x{code:02X})")
